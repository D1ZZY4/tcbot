-- The database functions that own the state transitions.
CREATE OR REPLACE FUNCTION %SCHEMA%.assign_moderation_action_external_ref() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF NEW.external_ref IS NULL OR btrim(NEW.external_ref) = '' THEN
        NEW.external_ref := substr(replace(gen_random_uuid()::text, '-', ''), 1, 16);
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.enforce_moderation_ban_evidence() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_requires_evidence boolean;
  v_case_status text;
  v_upload_status text;
  v_upload_required boolean;
BEGIN
  SELECT c.requires_evidence, c.status
    INTO v_requires_evidence, v_case_status
    FROM %SCHEMA%.moderation_cases AS c
    WHERE c.id = NEW.case_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Moderation case % does not exist', NEW.case_id;
  END IF;

  IF v_case_status IN ('resolved', 'dismissed', 'cancelled') THEN
    RAISE EXCEPTION 'Cannot add moderation actions to a closed case';
  END IF;

  IF NEW.evidence_upload_id IS NOT NULL THEN
    SELECT u.status, u.is_required
      INTO v_upload_status, v_upload_required
      FROM %SCHEMA%.moderation_evidence_uploads AS u
      WHERE u.id = NEW.evidence_upload_id
        AND u.case_id = NEW.case_id;

    IF NOT FOUND THEN
      RAISE EXCEPTION
        'Evidence upload % does not belong to moderation case %',
        NEW.evidence_upload_id, NEW.case_id;
    END IF;

    IF v_upload_status NOT IN ('completed', 'partial') THEN
      RAISE EXCEPTION 'Only completed or partial evidence uploads can be attached to an action';
    END IF;
  END IF;

  IF NEW.action_type <> 'ban' THEN
    RETURN NEW;
  END IF;

  -- Automated threshold bans may be created without evidence, but if an
  -- evidence batch is supplied it must be explicitly linked on the action.
  IF NEW.action_origin = 'automated' AND NOT v_requires_evidence THEN
    RETURN NEW;
  END IF;

  IF NEW.evidence_upload_id IS NULL THEN
    RAISE EXCEPTION
      'This ban requires an explicitly linked completed evidence upload';
  END IF;

  IF v_upload_status <> 'completed' OR NOT v_upload_required THEN
    RAISE EXCEPTION
      'Manual, system, and AI bans require a completed upload marked as required';
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.enqueue_reconcile_run(p_action_id bigint, p_requested_by_user_id bigint DEFAULT NULL::bigint, p_revision integer DEFAULT NULL::integer) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    v_action   %SCHEMA%.moderation_actions%ROWTYPE;
    v_run_id   bigint;
    v_revision integer;
    v_key      text;
BEGIN
    SELECT * INTO v_action
    FROM %SCHEMA%.moderation_actions
    WHERE id = p_action_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Moderation action % does not exist', p_action_id;
    END IF;

    v_revision := COALESCE(
        p_revision,
        (SELECT COALESCE(max(split_part(idempotency_key, 'v', 2)::integer), 0) + 1
           FROM %SCHEMA%.moderation_enforcement_runs
          WHERE action_id = p_action_id AND operation = 'reconcile')
    );

    v_key := format('moderation:%s:reconcile:v%s', p_action_id, v_revision);

    INSERT INTO %SCHEMA%.moderation_enforcement_runs
        (action_id, operation, idempotency_key, requested_by_user_id, status)
    VALUES
        (p_action_id, 'reconcile', v_key, p_requested_by_user_id, 'queued')
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id INTO v_run_id;

    IF v_run_id IS NULL THEN
        SELECT id INTO v_run_id
        FROM %SCHEMA%.moderation_enforcement_runs
        WHERE idempotency_key = v_key;
        RETURN v_run_id;
    END IF;

    IF v_action.scope_type = 'chat' THEN
        INSERT INTO %SCHEMA%.moderation_enforcement_targets (run_id, chat_id)
        VALUES (v_run_id, v_action.chat_id)
        ON CONFLICT (run_id, chat_id) DO NOTHING;
    ELSE
        INSERT INTO %SCHEMA%.moderation_enforcement_targets (run_id, chat_id)
        SELECT v_run_id, cc.chat_id
        FROM %SCHEMA%.connected_chats AS cc
        WHERE cc.is_active
        ON CONFLICT (run_id, chat_id) DO NOTHING;
    END IF;

    INSERT INTO %SCHEMA%.audit_events (event_key, entity_type, entity_id, subject_user_id, actor_user_id, payload)
    VALUES ('moderation.enforcement.reconcile_requested', 'enforcement_run', v_run_id::text,
            v_action.target_user_id, p_requested_by_user_id,
            jsonb_build_object('action_id', p_action_id, 'revision', v_revision));

    RETURN v_run_id;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.expire_due_moderation_actions() RETURNS bigint
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_expired_count bigint;
BEGIN
  -- * An expired ban closes its pending appeal in the same statement. A
  -- * pending appeal left behind can never be decided, because a decision
  -- * requires an active ban, and it keeps a review card alive for a
  -- * question that no longer exists. The review slot of the decision is
  -- * released for the same reason.
  WITH expired AS (
      UPDATE %SCHEMA%.moderation_actions
         SET status = 'expired',
             metadata = metadata - 'review_message_id' - 'review_timestamp'
       WHERE action_type IN ('ban', 'mute')
         AND status = 'active'
         AND expires_at IS NOT NULL
         AND expires_at <= now()
      RETURNING id
  ), withdrawn AS (
      UPDATE %SCHEMA%.moderation_appeals AS a
         SET status = 'withdrawn',
             resolved_at = now(),
             decision_note = 'Ban expired'
        FROM expired
       WHERE a.action_id = expired.id
         AND a.status = 'pending'
      RETURNING a.id
  )
  -- * The final projection references both CTEs, so the two updates are
  -- * one atomic statement.
  SELECT count(*), (SELECT count(*) FROM withdrawn)
    INTO v_expired_count
    FROM expired;

  RETURN v_expired_count;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.expire_due_moderation_actions_and_queue_revokes() RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    v_expired integer;
    v_queued  integer;
BEGIN
    v_expired := %SCHEMA%.expire_due_moderation_actions();
    v_queued  := %SCHEMA%.queue_revoke_enforcement_for_expired_actions();

    RETURN jsonb_build_object('expired_actions', v_expired,
                              'revoke_runs_created', v_queued);
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_moderation_action_update() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_repoint_source bigint := NULLIF(
        current_setting('tcbot.chat_repoint_source', true), ''
    )::bigint;
BEGIN
  -- * The metadata is the annotation of a decision, not a fact of it:
  -- * the review slot, the appeal link, the update counter, and the
  -- * reference of the previous proof live there. The facts below are
  -- * what a decision is, and they never change.
  --
  -- * The chat a decision belongs to is the one exception: Telegram
  -- * retires a basic group and hands the bot the id of the supergroup
  -- * that replaced it, so the history of that group has to follow the
  -- * new id. Only the repoint function performs that move, and it marks
  -- * the transaction it runs in; every other writer is refused.
  IF (NEW.chat_id IS DISTINCT FROM OLD.chat_id
      OR NEW.origin_chat_id IS DISTINCT FROM OLD.origin_chat_id)
     AND NOT (v_repoint_source IS NOT NULL
              AND (OLD.chat_id = v_repoint_source
                   OR OLD.origin_chat_id = v_repoint_source)) THEN
    RAISE EXCEPTION 'The chat of a moderation action is immutable; repoint the chat records instead';
  END IF;
  IF NEW.scope_type IS DISTINCT FROM OLD.scope_type
     OR NEW.action_type IS DISTINCT FROM OLD.action_type
     OR NEW.target_user_id IS DISTINCT FROM OLD.target_user_id
     OR NEW.actor_user_id IS DISTINCT FROM OLD.actor_user_id
     OR NEW.action_origin IS DISTINCT FROM OLD.action_origin
     OR NEW.reason IS DISTINCT FROM OLD.reason
     OR NEW.duration_seconds IS DISTINCT FROM OLD.duration_seconds
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
     OR NEW.external_ref IS DISTINCT FROM OLD.external_ref
     OR NEW.case_id IS DISTINCT FROM OLD.case_id
     OR NEW.evidence_upload_id IS DISTINCT FROM OLD.evidence_upload_id
     OR NEW.supersedes_action_id IS DISTINCT FROM OLD.supersedes_action_id THEN
    RAISE EXCEPTION 'Moderation action facts are immutable; create a new action instead';
  END IF;
  IF NEW.status = 'failed' AND NEW.action_type <> 'kick' THEN
    RAISE EXCEPTION 'Only a kick can carry the failed status';
  END IF;
  IF OLD.status IN ('revoked', 'expired', 'superseded')
     AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'Terminal moderation action status cannot be changed';
  END IF;
  IF OLD.status = 'active'
     AND NEW.status NOT IN ('active', 'revoked', 'expired', 'superseded') THEN
    RAISE EXCEPTION 'Invalid moderation action transition: % -> %', OLD.status, NEW.status;
  END IF;
  IF OLD.status = 'completed'
     AND NEW.status NOT IN ('completed', 'revoked')
     AND NOT (NEW.action_type = 'kick' AND NEW.status = 'failed') THEN
    RAISE EXCEPTION 'Invalid moderation action transition: % -> %', OLD.status, NEW.status;
  END IF;
  -- * A kick is the only one-shot decision with a second delivery step:
  -- * the ban lands, then the unban converts it into a rejoin. If either
  -- * step fails, the record moves to failed so history does not claim a
  -- * completed kick; the repair run moves it back once the unban lands.
  IF OLD.status = 'failed'
     AND NEW.status IS DISTINCT FROM OLD.status
     AND NOT (NEW.action_type = 'kick' AND NEW.status = 'completed') THEN
    RAISE EXCEPTION 'Invalid moderation action transition: % -> %', OLD.status, NEW.status;
  END IF;
  IF NEW.status = 'revoked' THEN
    NEW.revoked_at := COALESCE(OLD.revoked_at, NEW.revoked_at, now());
  ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
    NEW.revoked_at := NULL;
    NEW.revoked_by_user_id := NULL;
  END IF;
  IF NEW.status = 'expired'
     AND (NEW.expires_at IS NULL OR NEW.expires_at > now()) THEN
    RAISE EXCEPTION 'Only actions whose expiry time has passed can become expired';
  END IF;
  IF OLD.status = 'revoked' THEN
    IF NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
      RAISE EXCEPTION 'Revocation timestamp is immutable';
    END IF;
    IF NEW.revoked_by_user_id IS DISTINCT FROM OLD.revoked_by_user_id
       AND NEW.revoked_by_user_id IS NOT NULL THEN
      RAISE EXCEPTION 'Revocation actor is immutable; only FK-driven nullification is permitted';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_moderation_appeal_lifecycle() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'pending'
       OR NEW.resolved_at IS NOT NULL
       OR NEW.reviewed_by_user_id IS NOT NULL THEN
      RAISE EXCEPTION 'Moderation appeals must be created pending and unresolved';
    END IF;
    RETURN NEW;
  END IF;

  IF NEW.action_id IS DISTINCT FROM OLD.action_id
     OR NEW.appellant_user_id IS DISTINCT FROM OLD.appellant_user_id
     OR NEW.appeal_text IS DISTINCT FROM OLD.appeal_text
     OR NEW.submitted_at IS DISTINCT FROM OLD.submitted_at THEN
    RAISE EXCEPTION 'Appeal submission facts are immutable';
  END IF;

  IF OLD.status <> 'pending' THEN
    IF NEW.status IS DISTINCT FROM OLD.status
       OR NEW.resolved_at IS DISTINCT FROM OLD.resolved_at
       OR NEW.decision_note IS DISTINCT FROM OLD.decision_note
       OR NEW.reviewed_by_user_id IS DISTINCT FROM OLD.reviewed_by_user_id THEN
      RAISE EXCEPTION 'Resolved appeal decisions are immutable';
    END IF;
    RETURN NEW;
  END IF;

  IF NEW.status NOT IN ('pending','accepted','rejected','withdrawn') THEN
    RAISE EXCEPTION 'Invalid moderation appeal transition: % -> %', OLD.status, NEW.status;
  END IF;

  IF NEW.status = 'pending' THEN
    IF NEW.reviewed_by_user_id IS NOT NULL OR NEW.resolved_at IS NOT NULL THEN
      RAISE EXCEPTION 'Pending appeals cannot have review metadata';
    END IF;
  ELSE
    NEW.resolved_at := COALESCE(NEW.resolved_at, now());
  END IF;

  IF NEW.status IN ('accepted','rejected') AND NEW.reviewed_by_user_id IS NULL THEN
    RAISE EXCEPTION 'Accepted or rejected appeals require a reviewer';
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_moderation_case_insert() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  IF NEW.status NOT IN ('open', 'collecting_evidence')
     OR NEW.resolved_at IS NOT NULL
     OR NEW.closed_by_user_id IS NOT NULL THEN
    RAISE EXCEPTION
      'New moderation cases must start open or collecting_evidence without closing metadata';
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_moderation_case_update() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  IF NEW.public_id IS DISTINCT FROM OLD.public_id
     OR NEW.subject_user_id IS DISTINCT FROM OLD.subject_user_id
     OR NEW.case_type IS DISTINCT FROM OLD.case_type
     OR NEW.source IS DISTINCT FROM OLD.source
     OR NEW.requires_evidence IS DISTINCT FROM OLD.requires_evidence
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR (NEW.opened_by_user_id IS DISTINCT FROM OLD.opened_by_user_id
         AND NEW.opened_by_user_id IS NOT NULL) THEN
    RAISE EXCEPTION 'Moderation case identity, origin, creator, and evidence policy are immutable';
  END IF;
  IF OLD.status IN ('resolved', 'dismissed', 'cancelled') THEN
    IF NEW.status IS DISTINCT FROM OLD.status
       OR NEW.resolved_at IS DISTINCT FROM OLD.resolved_at
       OR (NEW.closed_by_user_id IS DISTINCT FROM OLD.closed_by_user_id
           AND NEW.closed_by_user_id IS NOT NULL) THEN
      RAISE EXCEPTION 'Closed moderation case decisions and closing actor are immutable';
    END IF;
  ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
    IF NOT (
      (OLD.status = 'open' AND NEW.status IN ('collecting_evidence','under_review','escalated','resolved','dismissed','cancelled'))
      OR (OLD.status = 'collecting_evidence' AND NEW.status IN ('open','evidence_failed','under_review','escalated','resolved','dismissed','cancelled'))
      OR (OLD.status = 'evidence_failed' AND NEW.status IN ('collecting_evidence','under_review','escalated','resolved','dismissed','cancelled'))
      OR (OLD.status = 'under_review' AND NEW.status IN ('collecting_evidence','escalated','resolved','dismissed','cancelled'))
      OR (OLD.status = 'escalated' AND NEW.status IN ('under_review','resolved','dismissed','cancelled'))
    ) THEN
      RAISE EXCEPTION 'Invalid moderation case status transition: % -> %', OLD.status, NEW.status;
    END IF;
  END IF;
  IF NEW.status IN ('resolved', 'dismissed', 'cancelled') THEN
    -- * The closing time belongs to the decision, so a caller may name
    -- * it. A case that does not name one is closed now.
    NEW.resolved_at := COALESCE(NEW.resolved_at, OLD.resolved_at, now());
  ELSE
    IF NEW.closed_by_user_id IS NOT NULL THEN
      RAISE EXCEPTION 'An open moderation case cannot have a closing actor';
    END IF;
    NEW.resolved_at := NULL;
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_moderation_enforcement_attempt() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.attempted_at < now() - make_interval(days => %SCHEMA%.retention_window_days('moderation_enforcement_attempts')) THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'Attempt history is append-only';
    END IF;

    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Attempt history is append-only';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM %SCHEMA%.moderation_enforcement_targets AS t
         WHERE t.id = NEW.target_id
           AND t.status = 'in_progress'
           AND t.attempt_count = NEW.attempt_number
    ) THEN
        RAISE EXCEPTION 'Attempt must match the currently in-progress target attempt';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_moderation_enforcement_run_identity() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  IF NEW.action_id IS DISTINCT FROM OLD.action_id
     OR NEW.operation IS DISTINCT FROM OLD.operation
     OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR (
       NEW.requested_by_user_id IS DISTINCT FROM OLD.requested_by_user_id
       AND NEW.requested_by_user_id IS NOT NULL
     ) THEN
    RAISE EXCEPTION 'Enforcement run identity and provenance are immutable';
  END IF;

  IF OLD.status = 'cancelled' AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'A cancelled enforcement run is terminal';
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_moderation_evidence_item() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_upload_status text;
  v_expected_count integer;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'Archived moderation evidence items are append-only';
  END IF;

  SELECT u.status, u.expected_item_count
    INTO v_upload_status, v_expected_count
    FROM %SCHEMA%.moderation_evidence_uploads AS u
    WHERE u.id = NEW.upload_id
    FOR UPDATE;

  IF v_upload_status IS DISTINCT FROM 'uploading' THEN
    RAISE EXCEPTION 'Evidence items can only be appended while their upload is in uploading state';
  END IF;

  IF NEW.item_order >= v_expected_count THEN
    RAISE EXCEPTION 'Evidence item order % exceeds expected upload size %',
      NEW.item_order, v_expected_count;
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_moderation_message_history() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Moderation message references are append-only';
  END IF;

  IF NEW.action_id IS DISTINCT FROM OLD.action_id
     OR NEW.chat_id IS DISTINCT FROM OLD.chat_id
     OR NEW.message_id IS DISTINCT FROM OLD.message_id
     OR NEW.message_kind IS DISTINCT FROM OLD.message_kind
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR (
       NEW.recorded_by_user_id IS DISTINCT FROM OLD.recorded_by_user_id
       AND NEW.recorded_by_user_id IS NOT NULL
     ) THEN
    RAISE EXCEPTION 'Moderation message references are immutable except recorder nullification';
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.prepare_moderation_action() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_previous %SCHEMA%.moderation_actions%ROWTYPE;
BEGIN
  IF NEW.scope_type IS NULL THEN
    NEW.scope_type := CASE WHEN NEW.action_type IN ('ban', 'mute') THEN 'community' ELSE 'chat' END;
  END IF;

  IF NEW.action_type IN ('warn', 'kick') AND NEW.origin_chat_id IS NULL THEN
    NEW.origin_chat_id := NEW.chat_id;
  END IF;

  IF NEW.scope_type = 'community'
     AND (NEW.action_type NOT IN ('ban', 'mute') OR NEW.chat_id IS NOT NULL) THEN
    RAISE EXCEPTION 'Community-scoped actions must be ban or mute and cannot carry a chat scope';
  END IF;

  IF NEW.scope_type = 'chat' THEN
    IF NEW.action_type NOT IN ('warn', 'kick') OR NEW.chat_id IS NULL THEN
      RAISE EXCEPTION 'Chat-scoped actions must be warn or kick and require a connected chat';
    END IF;
    -- * The primary group is registered inactive on purpose but still hosts
    -- * chat-scoped decisions. See the enforcement target trigger for the
    -- * session GUC that names that one chat.
    IF NOT EXISTS (
      SELECT 1 FROM %SCHEMA%.connected_chats AS cc
      WHERE cc.chat_id = NEW.chat_id
        AND (cc.is_active
             OR cc.chat_id = coalesce(
                 nullif(current_setting('tcbot.primary_chat_id', true), '')::bigint,
                 (SELECT cs.primary_chat_id FROM %SCHEMA%.community_settings AS cs
                   WHERE cs.singleton_key = 'global')
             ))
    ) THEN
      RAISE EXCEPTION 'Chat-scoped moderation requires an active connected chat';
    END IF;
  END IF;

  IF (NEW.action_type IN ('ban', 'mute') AND NEW.status <> 'active')
     OR (NEW.action_type IN ('warn', 'kick') AND NEW.status <> 'completed')
     OR NEW.revoked_at IS NOT NULL OR NEW.revoked_by_user_id IS NOT NULL
     OR (NEW.action_type IN ('ban', 'mute') AND NEW.expires_at IS NOT NULL
         AND NEW.expires_at <= NEW.created_at) THEN
    RAISE EXCEPTION 'New moderation actions must start in their initial status, have a future expiry, and have no revocation metadata';
  END IF;

  -- * The update guard compares expiry with the database transaction clock,
  -- * so the decision to expire has to use that same clock. The application
  -- * timestamp can lead the server; mixing the two aborts the new decision
  -- * in the narrow window where a timed action has just run out.
  UPDATE %SCHEMA%.moderation_actions AS a
     SET status = 'expired'
   WHERE a.scope_type = NEW.scope_type
     AND a.chat_id IS NOT DISTINCT FROM NEW.chat_id
     AND a.target_user_id = NEW.target_user_id
     AND a.action_type = NEW.action_type
     AND a.status = 'active'
     AND a.expires_at IS NOT NULL
     AND a.expires_at <= now();

  IF NEW.supersedes_action_id IS NOT NULL THEN
    IF NEW.action_type NOT IN ('ban', 'mute') OR NEW.status <> 'active' THEN
      RAISE EXCEPTION 'Only a new active ban or mute can supersede a previous active action';
    END IF;

    SELECT * INTO v_previous
      FROM %SCHEMA%.moderation_actions
     WHERE id = NEW.supersedes_action_id
     FOR UPDATE;

    IF NOT FOUND THEN
      RAISE EXCEPTION 'Action % selected for supersession does not exist', NEW.supersedes_action_id;
    END IF;

    IF v_previous.status <> 'active'
       OR v_previous.action_type <> NEW.action_type
       OR v_previous.scope_type <> NEW.scope_type
       OR v_previous.target_user_id <> NEW.target_user_id
       OR v_previous.chat_id IS DISTINCT FROM NEW.chat_id THEN
      RAISE EXCEPTION 'Only the current active action for the same scope, user, and action type can be superseded';
    END IF;

    UPDATE %SCHEMA%.moderation_actions
       SET status = 'superseded'
     WHERE id = v_previous.id;
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.prepare_moderation_enforcement_target() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_scope_type text;
  v_action_chat_id bigint;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'pending'
       OR NEW.attempt_count <> 0
       OR NEW.first_attempt_at IS NOT NULL
       OR NEW.last_attempt_at IS NOT NULL
       OR NEW.completed_at IS NOT NULL THEN
      RAISE EXCEPTION 'Enforcement targets must start pending and untouched';
    END IF;

    SELECT a.scope_type, a.chat_id
      INTO v_scope_type, v_action_chat_id
      FROM %SCHEMA%.moderation_enforcement_runs AS r
      JOIN %SCHEMA%.moderation_actions AS a ON a.id = r.action_id
     WHERE r.id = NEW.run_id;

    IF NOT FOUND THEN
      RAISE EXCEPTION 'Enforcement run % does not exist', NEW.run_id;
    END IF;

    -- * The deployment main group is registered as an inactive connected
    -- * chat, but moderation is deliberately enforced there. The application
    -- * publishes its id as a session GUC; every other inactive chat stays
    -- * excluded from durable delivery.
    IF NOT EXISTS (
      SELECT 1 FROM %SCHEMA%.connected_chats AS cc
      WHERE cc.chat_id = NEW.chat_id
        AND (cc.is_active
             OR cc.chat_id = coalesce(
                 nullif(current_setting('tcbot.primary_chat_id', true), '')::bigint,
                 (SELECT cs.primary_chat_id FROM %SCHEMA%.community_settings AS cs
                   WHERE cs.singleton_key = 'global')
             ))
    ) THEN
      RAISE EXCEPTION 'Enforcement target must be an active connected chat';
    END IF;

    IF v_scope_type = 'chat' AND v_action_chat_id IS DISTINCT FROM NEW.chat_id THEN
      RAISE EXCEPTION 'A chat-scoped action can only target its originating chat';
    END IF;

    RETURN NEW;
  END IF;

  IF NEW.run_id IS DISTINCT FROM OLD.run_id
     OR NEW.chat_id IS DISTINCT FROM OLD.chat_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Enforcement target identity is immutable';
  END IF;

  IF OLD.status = 'pending' AND NEW.status = 'in_progress' THEN
    NEW.attempt_count := OLD.attempt_count + 1;
    NEW.first_attempt_at := COALESCE(OLD.first_attempt_at, now());
    NEW.last_attempt_at := now();
    NEW.completed_at := NULL;
    NEW.next_retry_at := NULL;

  ELSIF OLD.status = 'failed' AND NEW.status = 'in_progress' THEN
    IF OLD.next_retry_at IS NOT NULL AND OLD.next_retry_at > now() THEN
      RAISE EXCEPTION 'Enforcement target retry deadline has not arrived';
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM %SCHEMA%.connected_chats AS cc
      WHERE cc.chat_id = NEW.chat_id
        AND (cc.is_active
             OR cc.chat_id = coalesce(
                 nullif(current_setting('tcbot.primary_chat_id', true), '')::bigint,
                 (SELECT cs.primary_chat_id FROM %SCHEMA%.community_settings AS cs
                   WHERE cs.singleton_key = 'global')
             ))
    ) THEN
      RAISE EXCEPTION 'Cannot retry enforcement for a chat that is no longer active';
    END IF;

    NEW.attempt_count := OLD.attempt_count + 1;
    NEW.first_attempt_at := COALESCE(OLD.first_attempt_at, now());
    NEW.last_attempt_at := now();
    NEW.completed_at := NULL;
    NEW.next_retry_at := NULL;

  ELSIF OLD.status = 'in_progress'
        AND NEW.status IN ('succeeded', 'skipped', 'failed') THEN
    NEW.completed_at := COALESCE(NEW.completed_at, now());

    IF NEW.status IN ('succeeded', 'skipped') THEN
      NEW.next_retry_at := NULL;
      NEW.last_error_kind := NULL;
      NEW.last_error_code := NULL;
      NEW.last_error_detail := NULL;
    END IF;

  ELSIF OLD.status = NEW.status AND OLD.status = 'failed' THEN
    -- * The retry deadline of a failed target is operational. A manual
    -- * replay brings the next attempt forward, and the attempt
    -- * history keeps the record of what actually happened, so the
    -- * fields of the last attempt stay as they are.
    IF NEW.next_retry_at IS NOT DISTINCT FROM OLD.next_retry_at THEN
      RAISE EXCEPTION 'Invalid enforcement target transition: % -> %', OLD.status, NEW.status;
    END IF;

    NEW.attempt_count := OLD.attempt_count;
    NEW.first_attempt_at := OLD.first_attempt_at;
    NEW.last_attempt_at := OLD.last_attempt_at;
    NEW.completed_at := OLD.completed_at;
    NEW.last_error_kind := OLD.last_error_kind;
    NEW.last_error_code := OLD.last_error_code;
    NEW.last_error_detail := OLD.last_error_detail;

  ELSE
    RAISE EXCEPTION 'Invalid enforcement target transition: % -> %', OLD.status, NEW.status;
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.queue_revoke_enforcement_for_expired_actions() RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    v_run_ids bigint[];
    v_count   integer;
BEGIN
    WITH inserted AS (
        INSERT INTO %SCHEMA%.moderation_enforcement_runs (
            action_id, operation, idempotency_key, requested_by_user_id, status
        )
        SELECT a.id,
               'revoke',
               format('moderation:%s:revoke:expire:v1', a.id),
               NULL,
               'queued'
        FROM %SCHEMA%.moderation_actions AS a
        WHERE a.status = 'expired'
          AND a.action_type IN ('ban', 'mute')
          AND a.expires_at IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM %SCHEMA%.moderation_enforcement_runs AS r
              WHERE r.action_id = a.id AND r.operation = 'revoke'
          )
        RETURNING id
    )
    SELECT array_agg(id), count(*) INTO v_run_ids, v_count FROM inserted;

    IF v_run_ids IS NULL THEN
        RETURN 0;
    END IF;

    INSERT INTO %SCHEMA%.moderation_enforcement_targets (run_id, chat_id)
    SELECT r.id, cc.chat_id
    FROM %SCHEMA%.moderation_enforcement_runs AS r
    -- * The main group is registered inactive on purpose but is a permanent
    -- * enforcement destination. Without this carve-out a timed ban or mute
    -- * would never be lifted there, leaving Telegram restricted forever.
    JOIN %SCHEMA%.connected_chats AS cc ON (
        cc.is_active
        OR cc.chat_id = coalesce(
            nullif(current_setting('tcbot.primary_chat_id', true), '')::bigint,
            (SELECT cs.primary_chat_id FROM %SCHEMA%.community_settings AS cs
              WHERE cs.singleton_key = 'global')
        )
    )
    WHERE r.id = ANY(v_run_ids)
      AND NOT EXISTS (
          SELECT 1 FROM %SCHEMA%.moderation_enforcement_targets AS t
          WHERE t.run_id = r.id
      );

    RETURN v_count;
END;
$$;

-- * The attempt ceiling mirrors enforcement_db.MAX_ATTEMPTS. A stuck target
-- * that already used its budget must become terminal: a failed row with a
-- * due next_retry_at would be claimed again and increment the count past the
-- * ceiling, issuing one more Telegram delivery than the worker ever allows.

CREATE OR REPLACE FUNCTION %SCHEMA%.reconcile_stuck_enforcement_targets(
    p_stale_after interval DEFAULT '00:15:00'::interval,
    p_max_attempts integer DEFAULT 3
) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    v_count integer;
    v_ids   bigint[];
    v_first bigint;
BEGIN
    WITH recovered AS (
        UPDATE %SCHEMA%.moderation_enforcement_targets AS t
           SET status = 'failed',
               next_retry_at = CASE
                   WHEN t.attempt_count < p_max_attempts THEN now()
                   ELSE NULL
               END,
               last_error_kind = CASE
                   WHEN t.attempt_count < p_max_attempts THEN 'worker_timeout'
                   ELSE 'attempts_exhausted'
               END,
               last_error_detail = CASE
                   WHEN t.attempt_count < p_max_attempts
                       THEN 'Target stayed in progress beyond the stale window and was released for retry'
                   ELSE 'Target stayed in progress beyond the stale window and exhausted its attempt budget'
               END,
               updated_at = now()
         WHERE t.status = 'in_progress'
           AND COALESCE(t.last_attempt_at, t.updated_at) < clock_timestamp() - p_stale_after
           AND EXISTS (
               SELECT 1 FROM %SCHEMA%.moderation_enforcement_runs AS r
               WHERE r.id = t.run_id AND r.status IN ('queued', 'running')
           )
        RETURNING t.id
    )
    SELECT array_agg(id), count(*) INTO v_ids, v_count FROM recovered;

    IF v_count > 0 THEN
        v_first := v_ids[1];
        INSERT INTO %SCHEMA%.audit_events (event_key, entity_type, entity_id, payload)
        VALUES ('moderation.enforcement.recovered', 'enforcement_target', v_first::text,
                jsonb_build_object('recovered_targets', v_count,
                                   'recovered_ids', to_jsonb(v_ids),
                                   'stale_after', p_stale_after::text));
    END IF;

    RETURN v_count;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.refresh_moderation_enforcement_run() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_run_id bigint := COALESCE(NEW.run_id, OLD.run_id);
  v_total integer; v_success integer; v_failed integer; v_skipped integer;
  v_pending integer; v_running integer; v_status text; v_finished timestamptz;
BEGIN
  SELECT count(*)::integer,
         count(*) FILTER (WHERE status = 'succeeded')::integer,
         count(*) FILTER (WHERE status = 'failed')::integer,
         count(*) FILTER (WHERE status = 'skipped')::integer,
         count(*) FILTER (WHERE status = 'pending')::integer,
         count(*) FILTER (WHERE status = 'in_progress')::integer
    INTO v_total, v_success, v_failed, v_skipped, v_pending, v_running
    FROM %SCHEMA%.moderation_enforcement_targets WHERE run_id = v_run_id;

  IF v_total = 0 THEN
    v_status := 'queued'; v_finished := NULL;
  ELSIF v_running > 0 THEN
    v_status := 'running'; v_finished := NULL;
  ELSIF v_pending > 0 THEN
    v_status := 'queued'; v_finished := NULL;
  ELSIF v_failed > 0 AND v_success + v_skipped > 0 THEN
    v_status := 'partial'; v_finished := now();
  ELSIF v_failed > 0 THEN
    v_status := 'failed'; v_finished := now();
  ELSE
    v_status := 'completed'; v_finished := now();
  END IF;

  UPDATE %SCHEMA%.moderation_enforcement_runs
     SET target_count = v_total,
         succeeded_count = v_success,
         failed_count = v_failed,
         skipped_count = v_skipped,
         status = v_status,
         started_at = CASE
           WHEN v_running > 0 OR v_success + v_failed + v_skipped > 0
             THEN COALESCE(started_at, now())
           ELSE started_at
         END,
         finished_at = v_finished,
         updated_at = now()
   WHERE id = v_run_id;
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.validate_moderation_case_rule_scope() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_scope_type text;
  v_rule_chat_id bigint;
  v_version_status text;
BEGIN
  SELECT rs.scope_type, rs.chat_id, rsv.status
    INTO v_scope_type, v_rule_chat_id, v_version_status
    FROM %SCHEMA%.moderation_cases AS c
    JOIN %SCHEMA%.rule_items AS ri ON ri.id = NEW.rule_item_id
    JOIN %SCHEMA%.rule_set_versions AS rsv ON rsv.id = ri.rule_set_version_id
    JOIN %SCHEMA%.rule_sets AS rs ON rs.id = rsv.rule_set_id
   WHERE c.id = NEW.case_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Moderation case or rule item does not exist';
  END IF;
  IF v_version_status = 'draft' THEN
    RAISE EXCEPTION 'Draft rules cannot be attached to moderation cases';
  END IF;
  IF NEW.context_chat_id IS NOT NULL
     AND NOT EXISTS (
       SELECT 1 FROM %SCHEMA%.connected_chats AS cc WHERE cc.chat_id = NEW.context_chat_id
     ) THEN
    RAISE EXCEPTION 'Context chat is not connected to this community';
  END IF;
  IF v_scope_type = 'chat' AND v_rule_chat_id IS DISTINCT FROM NEW.context_chat_id THEN
    RAISE EXCEPTION 'Chat-scoped rule must match the moderation case context chat';
  END IF;
  IF v_scope_type = 'community' AND v_rule_chat_id IS NOT NULL THEN
    RAISE EXCEPTION 'Community-scoped rule cannot contain a chat scope';
  END IF;
  RETURN NEW;
END;
$$;
