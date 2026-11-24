-- The database functions that own the state transitions.
CREATE OR REPLACE FUNCTION %SCHEMA%.automation_snapshot_run_steps(p_run_id bigint) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    v_run       %SCHEMA%.automation_runs%ROWTYPE;
    v_status    text;
    v_step      record;
    v_count     integer := 0;
    v_inserted  integer;
BEGIN
    SELECT * INTO v_run
    FROM %SCHEMA%.automation_runs
    WHERE id = p_run_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Automation run % does not exist', p_run_id;
    END IF;

    IF v_run.status NOT IN ('queued', 'running') THEN
        RAISE EXCEPTION 'Automation run % is % and cannot receive new steps', p_run_id, v_run.status;
    END IF;

    SELECT rsv.status INTO v_status
    FROM %SCHEMA%.automation_policy_versions AS rsv
    WHERE rsv.id = v_run.policy_version_id;

    IF v_status IS DISTINCT FROM 'published' THEN
        RAISE EXCEPTION 'Automation run % does not reference a published policy version', p_run_id;
    END IF;

    FOR v_step IN
        SELECT s.step AS step, (s.ord - 1)::integer AS step_order
        FROM %SCHEMA%.automation_policy_versions AS rsv
        CROSS JOIN LATERAL jsonb_array_elements(rsv.steps_definition)
             WITH ORDINALITY AS s(step, ord)
        WHERE rsv.id = v_run.policy_version_id
    LOOP
        INSERT INTO %SCHEMA%.automation_run_steps
            (run_id, step_key, step_order, step_type, config_snapshot)
        VALUES
            (p_run_id,
             v_step.step->>'key',
             v_step.step_order,
             v_step.step->>'type',
             COALESCE(v_step.step->'config', '{}'::jsonb))
        ON CONFLICT DO NOTHING;
        GET DIAGNOSTICS v_inserted = ROW_COUNT;
        v_count := v_count + v_inserted;
    END LOOP;

    RETURN v_count;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_automation_event_history() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  RAISE EXCEPTION 'Automation event history is append-only';
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_automation_policy_scope() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  IF NEW.scope_type = 'chat' AND NOT EXISTS (
    SELECT 1 FROM %SCHEMA%.connected_chats AS cc
    WHERE cc.chat_id = NEW.chat_id AND cc.is_active
  ) THEN
    RAISE EXCEPTION 'Chat-scoped automation policy requires an active connected chat';
  END IF;

  IF TG_OP = 'UPDATE' AND (
    NEW.policy_key IS DISTINCT FROM OLD.policy_key
    OR NEW.scope_type IS DISTINCT FROM OLD.scope_type
    OR NEW.chat_id IS DISTINCT FROM OLD.chat_id
  ) THEN
    RAISE EXCEPTION 'Automation policy key and scope identity are immutable';
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_automation_policy_version() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  PERFORM %SCHEMA%.validate_automation_policy_definition(
    NEW.trigger_definition, NEW.conditions, NEW.steps_definition
  );

  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'draft'
       OR NEW.published_at IS NOT NULL
       OR NEW.published_by_user_id IS NOT NULL THEN
      RAISE EXCEPTION 'Automation policy versions must be created as unpublished drafts';
    END IF;
    RETURN NEW;
  END IF;

  IF NEW.policy_id IS DISTINCT FROM OLD.policy_id
     OR NEW.version_number IS DISTINCT FROM OLD.version_number
     OR NEW.definition_schema_version IS DISTINCT FROM OLD.definition_schema_version
     OR NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Automation policy version identity, schema version, and creator are immutable';
  END IF;

  IF OLD.status <> 'draft' THEN
    IF NEW.trigger_definition IS DISTINCT FROM OLD.trigger_definition
       OR NEW.conditions IS DISTINCT FROM OLD.conditions
       OR NEW.steps_definition IS DISTINCT FROM OLD.steps_definition
       OR NEW.change_summary IS DISTINCT FROM OLD.change_summary
       OR NEW.published_at IS DISTINCT FROM OLD.published_at
       OR NEW.published_by_user_id IS DISTINCT FROM OLD.published_by_user_id
       OR NEW.status NOT IN (OLD.status, 'superseded', 'archived') THEN
      RAISE EXCEPTION 'Published automation policy versions are immutable';
    END IF;
  END IF;

  IF OLD.status = 'draft' AND NEW.status NOT IN ('draft', 'published', 'archived') THEN
    RAISE EXCEPTION 'Invalid automation policy version transition: % -> %', OLD.status, NEW.status;
  END IF;

  IF NEW.status = 'published' THEN
    IF NEW.published_by_user_id IS NULL THEN
      RAISE EXCEPTION 'Publishing an automation policy version requires a publisher';
    END IF;
    NEW.published_at := COALESCE(NEW.published_at, now());
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_automation_run_insert() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_scope text;
  v_policy_chat_id bigint;
  v_version_status text;
BEGIN
  IF NEW.status <> 'queued' OR NEW.started_at IS NOT NULL OR NEW.finished_at IS NOT NULL THEN
    RAISE EXCEPTION 'Automation runs must be created queued and not yet started';
  END IF;

  SELECT p.scope_type, p.chat_id, v.status
    INTO v_scope, v_policy_chat_id, v_version_status
    FROM %SCHEMA%.automation_policy_versions AS v
    JOIN %SCHEMA%.automation_policies AS p ON p.id = v.policy_id
   WHERE v.id = NEW.policy_version_id
     AND p.is_enabled;

  IF NOT FOUND OR v_version_status <> 'published' THEN
    RAISE EXCEPTION 'Automation run requires an enabled policy with a published version';
  END IF;

  IF NEW.context_chat_id IS NOT NULL
     AND NOT EXISTS (
       SELECT 1 FROM %SCHEMA%.connected_chats AS cc
       WHERE cc.chat_id = NEW.context_chat_id AND cc.is_active
     ) THEN
    RAISE EXCEPTION 'Automation run context must be an active connected chat';
  END IF;

  IF v_scope = 'chat' AND v_policy_chat_id IS DISTINCT FROM NEW.context_chat_id THEN
    RAISE EXCEPTION 'Chat-scoped automation must execute in its configured chat';
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_automation_run_step() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_run_status text;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'pending' OR NEW.attempt_count <> 0
       OR NEW.started_at IS NOT NULL OR NEW.finished_at IS NOT NULL THEN
      RAISE EXCEPTION 'Automation run steps must start pending and untouched';
    END IF;

    SELECT status INTO v_run_status
      FROM %SCHEMA%.automation_runs
     WHERE id = NEW.run_id;

    IF NOT FOUND OR v_run_status NOT IN ('queued', 'running') THEN
      RAISE EXCEPTION 'Automation steps can only be added to a queued or running run';
    END IF;

    RETURN NEW;
  END IF;

  IF NEW.run_id IS DISTINCT FROM OLD.run_id
     OR NEW.step_key IS DISTINCT FROM OLD.step_key
     OR NEW.step_order IS DISTINCT FROM OLD.step_order
     OR NEW.step_type IS DISTINCT FROM OLD.step_type
     OR NEW.config_snapshot IS DISTINCT FROM OLD.config_snapshot
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Automation run step definition and identity are immutable';
  END IF;

  IF OLD.status = 'pending' AND NEW.status = 'in_progress' THEN
    NEW.attempt_count := OLD.attempt_count + 1;
    NEW.started_at := COALESCE(OLD.started_at, now());
    NEW.finished_at := NULL;
    NEW.next_retry_at := NULL;
  ELSIF OLD.status = 'failed' AND NEW.status = 'in_progress' THEN
    IF OLD.next_retry_at IS NOT NULL AND OLD.next_retry_at > now() THEN
      RAISE EXCEPTION 'Automation step retry deadline has not arrived';
    END IF;
    NEW.attempt_count := OLD.attempt_count + 1;
    NEW.started_at := COALESCE(OLD.started_at, now());
    NEW.finished_at := NULL;
    NEW.next_retry_at := NULL;
  ELSIF OLD.status = 'in_progress' AND NEW.status IN ('completed', 'failed', 'skipped') THEN
    NEW.finished_at := COALESCE(NEW.finished_at, now());
    IF NEW.status IN ('completed', 'skipped') THEN
      NEW.next_retry_at := NULL;
      NEW.error_code := NULL;
      NEW.error_detail := NULL;
    END IF;
  ELSIF OLD.status IN ('pending', 'failed') AND NEW.status = 'cancelled' THEN
    NEW.finished_at := COALESCE(NEW.finished_at, now());
  ELSE
    RAISE EXCEPTION 'Invalid automation step transition: % -> %', OLD.status, NEW.status;
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_automation_run_update() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  IF NEW.public_id IS DISTINCT FROM OLD.public_id
     OR NEW.policy_version_id IS DISTINCT FROM OLD.policy_version_id
     OR NEW.event_id IS DISTINCT FROM OLD.event_id
     OR NEW.subject_user_id IS DISTINCT FROM OLD.subject_user_id
     OR NEW.context_chat_id IS DISTINCT FROM OLD.context_chat_id
     OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Automation run identity is immutable';
  END IF;

  IF OLD.status IN ('completed', 'skipped', 'cancelled')
     AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'Terminal automation run status cannot be changed';
  END IF;

  IF OLD.status = 'queued' AND NEW.status NOT IN ('queued', 'running', 'skipped', 'cancelled', 'failed') THEN
    RAISE EXCEPTION 'Invalid automation run transition: % -> %', OLD.status, NEW.status;
  END IF;

  IF OLD.status = 'running' AND NEW.status NOT IN ('running', 'completed', 'partial', 'failed', 'cancelled') THEN
    RAISE EXCEPTION 'Invalid automation run transition: % -> %', OLD.status, NEW.status;
  END IF;

  IF OLD.status IN ('failed', 'partial') AND NEW.status NOT IN (OLD.status, 'running') THEN
    RAISE EXCEPTION 'Failed or partial automation run can only be retried or retained';
  END IF;

  IF NEW.status IN ('completed', 'partial', 'failed', 'skipped', 'cancelled') THEN
    NEW.finished_at := COALESCE(NEW.finished_at, now());
  ELSE
    NEW.finished_at := NULL;
  END IF;

  IF NEW.status = 'running' THEN
    NEW.started_at := COALESCE(OLD.started_at, NEW.started_at, now());
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_automation_step_attempt() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.attempted_at < now() - make_interval(days => %SCHEMA%.retention_window_days('automation_run_step_attempts')) THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'Automation step attempt history is append-only';
    END IF;

    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Automation step attempt history is append-only';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM %SCHEMA%.automation_run_steps AS s
         WHERE s.id = NEW.step_id
           AND s.status = 'in_progress'
           AND s.attempt_count = NEW.attempt_number
    ) THEN
        RAISE EXCEPTION 'Automation attempt must match the current in-progress step attempt';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_broadcast_attempt() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.attempted_at < now() - make_interval(days => %SCHEMA%.retention_window_days('broadcast_attempts')) THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'Broadcast attempt history is append-only';
    END IF;

    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Broadcast attempt history is append-only';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM %SCHEMA%.broadcast_targets AS t
         WHERE t.id = NEW.target_id
           AND t.status = 'in_progress'
           AND t.attempt_count = NEW.attempt_number
    ) THEN
        RAISE EXCEPTION 'Broadcast attempt must match the current in-progress target attempt';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_broadcast_campaign() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  PERFORM %SCHEMA%.validate_broadcast_audience_filter(NEW.audience_filter);

  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'draft' OR NEW.started_at IS NOT NULL OR NEW.finished_at IS NOT NULL
       OR NEW.target_count <> 0 OR NEW.succeeded_count <> 0
       OR NEW.failed_count <> 0 OR NEW.skipped_count <> 0 THEN
      RAISE EXCEPTION 'Broadcast campaigns must be created as untouched drafts';
    END IF;
    RETURN NEW;
  END IF;

  IF NEW.public_id IS DISTINCT FROM OLD.public_id
     OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
     OR NEW.requested_by_user_id IS DISTINCT FROM OLD.requested_by_user_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Broadcast campaign identity and creator are immutable';
  END IF;

  IF OLD.status <> 'draft' AND (
    NEW.title IS DISTINCT FROM OLD.title
    OR NEW.message_text IS DISTINCT FROM OLD.message_text
    OR NEW.parse_mode IS DISTINCT FROM OLD.parse_mode
    OR NEW.message_payload IS DISTINCT FROM OLD.message_payload
    OR NEW.audience_filter IS DISTINCT FROM OLD.audience_filter
    OR NEW.scheduled_at IS DISTINCT FROM OLD.scheduled_at
  ) THEN
    RAISE EXCEPTION 'Broadcast content and audience are immutable after leaving draft';
  END IF;

  IF OLD.status IN ('completed', 'cancelled') AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'Completed or cancelled broadcast campaigns are immutable';
  END IF;

  IF OLD.status = 'draft' AND NEW.status NOT IN ('draft', 'scheduled', 'queued', 'cancelled') THEN
    RAISE EXCEPTION 'Invalid broadcast campaign transition: % -> %', OLD.status, NEW.status;
  ELSIF OLD.status = 'scheduled' AND NEW.status NOT IN ('scheduled', 'queued', 'cancelled') THEN
    RAISE EXCEPTION 'Invalid broadcast campaign transition: % -> %', OLD.status, NEW.status;
  ELSIF OLD.status = 'queued' AND NEW.status NOT IN ('queued', 'running', 'cancelled') THEN
    RAISE EXCEPTION 'Invalid broadcast campaign transition: % -> %', OLD.status, NEW.status;
  ELSIF OLD.status = 'running' AND NEW.status NOT IN ('running', 'completed', 'partial', 'failed', 'cancelled') THEN
    RAISE EXCEPTION 'Invalid broadcast campaign transition: % -> %', OLD.status, NEW.status;
  ELSIF OLD.status IN ('partial', 'failed') AND NEW.status NOT IN (OLD.status, 'running', 'cancelled') THEN
    RAISE EXCEPTION 'Partial or failed broadcast campaigns can only be retried or cancelled';
  END IF;

  IF NEW.status = 'running' THEN
    NEW.started_at := COALESCE(OLD.started_at, NEW.started_at, now());
    NEW.finished_at := NULL;
  ELSIF NEW.status IN ('completed', 'partial', 'failed', 'cancelled') THEN
    NEW.finished_at := COALESCE(NEW.finished_at, now());
  ELSE
    NEW.finished_at := NULL;
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.prepare_broadcast_target() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_campaign_status text;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'pending' OR NEW.attempt_count <> 0
       OR NEW.first_attempt_at IS NOT NULL OR NEW.last_attempt_at IS NOT NULL
       OR NEW.completed_at IS NOT NULL THEN
      RAISE EXCEPTION 'Broadcast targets must start pending and untouched';
    END IF;

    SELECT status INTO v_campaign_status
      FROM %SCHEMA%.broadcast_campaigns
     WHERE id = NEW.campaign_id;

    IF NOT FOUND OR v_campaign_status NOT IN ('queued', 'running') THEN
      RAISE EXCEPTION 'Broadcast targets can only be added to queued or running campaigns';
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM %SCHEMA%.connected_chats AS cc
      WHERE cc.chat_id = NEW.chat_id AND cc.is_active
    ) THEN
      RAISE EXCEPTION 'Broadcast target must be an active connected chat';
    END IF;

    RETURN NEW;
  END IF;

  IF NEW.campaign_id IS DISTINCT FROM OLD.campaign_id
     OR NEW.chat_id IS DISTINCT FROM OLD.chat_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Broadcast target identity is immutable';
  END IF;

  IF OLD.status = 'pending' AND NEW.status = 'in_progress' THEN
    NEW.attempt_count := OLD.attempt_count + 1;
    NEW.first_attempt_at := COALESCE(OLD.first_attempt_at, now());
    NEW.last_attempt_at := now();
    NEW.completed_at := NULL;
    NEW.next_retry_at := NULL;
  ELSIF OLD.status = 'failed' AND NEW.status = 'in_progress' THEN
    IF OLD.next_retry_at IS NOT NULL AND OLD.next_retry_at > now() THEN
      RAISE EXCEPTION 'Broadcast retry deadline has not arrived';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM %SCHEMA%.connected_chats AS cc
      WHERE cc.chat_id = NEW.chat_id AND cc.is_active
    ) THEN
      RAISE EXCEPTION 'Cannot retry a broadcast to a chat that is no longer active';
    END IF;
    NEW.attempt_count := OLD.attempt_count + 1;
    NEW.first_attempt_at := COALESCE(OLD.first_attempt_at, now());
    NEW.last_attempt_at := now();
    NEW.completed_at := NULL;
    NEW.next_retry_at := NULL;
  ELSIF OLD.status = 'in_progress' AND NEW.status IN ('succeeded', 'failed', 'skipped') THEN
    NEW.completed_at := COALESCE(NEW.completed_at, now());
    IF NEW.status IN ('succeeded', 'skipped') THEN
      NEW.next_retry_at := NULL;
      NEW.last_error_kind := NULL;
      NEW.last_error_code := NULL;
      NEW.last_error_detail := NULL;
    END IF;
  ELSE
    RAISE EXCEPTION 'Invalid broadcast target transition: % -> %', OLD.status, NEW.status;
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.queue_broadcast_campaign(p_campaign_id bigint) RETURNS integer
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_campaign %SCHEMA%.broadcast_campaigns%ROWTYPE;
  v_mode text;
  v_item jsonb;
  v_value text;
  v_chat_id bigint;
  v_chat_ids bigint[] := ARRAY[]::bigint[];
  v_existing_count integer;
  v_inserted_count integer;
  v_expected_count integer;
  v_active_count integer;
BEGIN
  SELECT * INTO v_campaign
    FROM %SCHEMA%.broadcast_campaigns
   WHERE id = p_campaign_id
   FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Broadcast campaign % does not exist', p_campaign_id;
  END IF;

  IF v_campaign.status IN ('draft', 'scheduled') THEN
    UPDATE %SCHEMA%.broadcast_campaigns
       SET status = 'queued'
     WHERE id = p_campaign_id;
  ELSIF v_campaign.status NOT IN ('queued', 'running') THEN
    RAISE EXCEPTION 'Campaign in status % cannot be queued', v_campaign.status;
  END IF;

  SELECT COUNT(*)::integer INTO v_existing_count
    FROM %SCHEMA%.broadcast_targets
   WHERE campaign_id = p_campaign_id;

  IF v_existing_count > 0 THEN
    RETURN v_existing_count;
  END IF;

  PERFORM %SCHEMA%.validate_broadcast_audience_filter(v_campaign.audience_filter);
  v_mode := COALESCE(v_campaign.audience_filter->>'mode', 'all_active');

  IF v_mode IN ('include', 'exclude') THEN
    FOR v_item IN
      SELECT value FROM jsonb_array_elements(v_campaign.audience_filter->'chat_ids') AS items(value)
    LOOP
      v_value := CASE
        WHEN jsonb_typeof(v_item) = 'string' THEN v_item #>> '{}'
        ELSE v_item::text
      END;
      v_chat_id := v_value::bigint;
      v_chat_ids := array_append(v_chat_ids, v_chat_id);
    END LOOP;
  END IF;

  IF v_mode = 'include' THEN
    SELECT COUNT(*)::integer INTO v_expected_count
      FROM %SCHEMA%.connected_chats AS cc
     WHERE cc.is_active AND cc.chat_id = ANY(v_chat_ids);

    IF v_expected_count <> cardinality(v_chat_ids) THEN
      RAISE EXCEPTION 'Broadcast include filter contains a chat that is not currently active and connected';
    END IF;

    INSERT INTO %SCHEMA%.broadcast_targets (campaign_id, chat_id)
    SELECT p_campaign_id, cc.chat_id
      FROM %SCHEMA%.connected_chats AS cc
     WHERE cc.is_active AND cc.chat_id = ANY(v_chat_ids)
    ON CONFLICT (campaign_id, chat_id) DO NOTHING;

  ELSIF v_mode = 'exclude' THEN
    INSERT INTO %SCHEMA%.broadcast_targets (campaign_id, chat_id)
    SELECT p_campaign_id, cc.chat_id
      FROM %SCHEMA%.connected_chats AS cc
     WHERE cc.is_active AND NOT (cc.chat_id = ANY(v_chat_ids))
    ON CONFLICT (campaign_id, chat_id) DO NOTHING;

  ELSE
    INSERT INTO %SCHEMA%.broadcast_targets (campaign_id, chat_id)
    SELECT p_campaign_id, cc.chat_id
      FROM %SCHEMA%.connected_chats AS cc
     WHERE cc.is_active
    ON CONFLICT (campaign_id, chat_id) DO NOTHING;
  END IF;

  GET DIAGNOSTICS v_inserted_count = ROW_COUNT;

  IF v_inserted_count = 0 THEN
    RAISE EXCEPTION 'Broadcast audience resolved to zero active connected chats';
  END IF;

  RETURN v_inserted_count;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.refresh_automation_run() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_run_id bigint := COALESCE(NEW.run_id, OLD.run_id);
  v_total integer;
  v_completed integer;
  v_failed integer;
  v_skipped integer;
  v_cancelled integer;
  v_pending integer;
  v_running integer;
  v_attempted integer;
  v_status text;
BEGIN
  SELECT
    COUNT(*)::integer,
    COUNT(*) FILTER (WHERE status = 'completed')::integer,
    COUNT(*) FILTER (WHERE status = 'failed')::integer,
    COUNT(*) FILTER (WHERE status = 'skipped')::integer,
    COUNT(*) FILTER (WHERE status = 'cancelled')::integer,
    COUNT(*) FILTER (WHERE status = 'pending')::integer,
    COUNT(*) FILTER (WHERE status = 'in_progress')::integer,
    COUNT(*) FILTER (WHERE attempt_count > 0 OR status <> 'pending')::integer
  INTO v_total, v_completed, v_failed, v_skipped, v_cancelled,
       v_pending, v_running, v_attempted
  FROM %SCHEMA%.automation_run_steps
  WHERE run_id = v_run_id;

  IF v_total = 0 THEN
    v_status := 'queued';
  ELSIF v_running > 0 THEN
    v_status := 'running';
  ELSIF v_pending > 0 THEN
    v_status := CASE WHEN v_attempted > 0 THEN 'running' ELSE 'queued' END;
  ELSIF v_failed > 0 AND (v_completed + v_skipped) > 0 THEN
    v_status := 'partial';
  ELSIF v_failed > 0 THEN
    v_status := 'failed';
  ELSIF v_cancelled = v_total THEN
    v_status := 'cancelled';
  ELSIF v_cancelled > 0 AND (v_completed + v_skipped) > 0 THEN
    v_status := 'partial';
  ELSIF v_skipped = v_total THEN
    v_status := 'skipped';
  ELSE
    v_status := 'completed';
  END IF;

  UPDATE %SCHEMA%.automation_runs
     SET status = v_status,
         outcome = v_status,
         started_at = CASE
           WHEN v_attempted > 0 THEN COALESCE(started_at, now())
           ELSE started_at
         END,
         finished_at = CASE
           WHEN v_status IN ('completed', 'partial', 'failed', 'skipped', 'cancelled') THEN now()
           ELSE NULL
         END,
         updated_at = now()
   WHERE id = v_run_id;

  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.refresh_broadcast_campaign() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_campaign_id bigint := COALESCE(NEW.campaign_id, OLD.campaign_id);
  v_total integer;
  v_success integer;
  v_failed integer;
  v_skipped integer;
  v_pending integer;
  v_running integer;
  v_status text;
  v_existing_status text;
  v_started_at timestamptz;
BEGIN
  SELECT status, started_at INTO v_existing_status, v_started_at
    FROM %SCHEMA%.broadcast_campaigns
   WHERE id = v_campaign_id;

  SELECT COUNT(*)::integer,
         COUNT(*) FILTER (WHERE status = 'succeeded')::integer,
         COUNT(*) FILTER (WHERE status = 'failed')::integer,
         COUNT(*) FILTER (WHERE status = 'skipped')::integer,
         COUNT(*) FILTER (WHERE status = 'pending')::integer,
         COUNT(*) FILTER (WHERE status = 'in_progress')::integer
    INTO v_total, v_success, v_failed, v_skipped, v_pending, v_running
    FROM %SCHEMA%.broadcast_targets
   WHERE campaign_id = v_campaign_id;

  v_status := v_existing_status;

  IF v_existing_status IN ('queued', 'running', 'partial', 'failed') AND v_total > 0 THEN
    IF v_running > 0 THEN
      v_status := 'running';
    ELSIF v_pending > 0 THEN
      v_status := CASE WHEN v_started_at IS NULL THEN 'queued' ELSE 'running' END;
    ELSIF v_failed > 0 AND v_success + v_skipped > 0 THEN
      v_status := 'partial';
    ELSIF v_failed > 0 THEN
      v_status := 'failed';
    ELSE
      v_status := 'completed';
    END IF;
  END IF;

  UPDATE %SCHEMA%.broadcast_campaigns
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
         finished_at = CASE
           WHEN v_status IN ('completed', 'partial', 'failed') THEN now()
           ELSE NULL
         END,
         updated_at = now()
   WHERE id = v_campaign_id;

  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.validate_automation_policy_definition(p_trigger_definition jsonb, p_conditions jsonb, p_steps_definition jsonb) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $_$
DECLARE
  v_step jsonb;
  v_key text;
  v_type text;
  v_seen_keys text[] := ARRAY[]::text[];
BEGIN
  IF jsonb_typeof(p_trigger_definition) <> 'object'
     OR NOT (p_trigger_definition ? 'event')
     OR jsonb_typeof(p_trigger_definition->'event') <> 'string'
     OR btrim(p_trigger_definition->>'event') = '' THEN
    RAISE EXCEPTION 'Automation trigger_definition requires a non-empty string event';
  END IF;

  IF jsonb_typeof(p_conditions) <> 'object' THEN
    RAISE EXCEPTION 'Automation conditions must be a JSON object';
  END IF;

  IF jsonb_typeof(p_steps_definition) <> 'array'
     OR jsonb_array_length(p_steps_definition) = 0 THEN
    RAISE EXCEPTION 'Automation steps_definition must be a non-empty JSON array';
  END IF;

  FOR v_step IN SELECT value FROM jsonb_array_elements(p_steps_definition) AS items(value)
  LOOP
    IF jsonb_typeof(v_step) <> 'object' THEN
      RAISE EXCEPTION 'Every automation step definition must be a JSON object';
    END IF;

    v_key := v_step->>'key';
    v_type := v_step->>'type';

    IF v_key IS NULL OR btrim(v_key) = ''
       OR v_key !~ '^[a-z0-9][a-z0-9._-]*$' THEN
      RAISE EXCEPTION 'Every automation step requires a valid unique key';
    END IF;

    IF v_key = ANY(v_seen_keys) THEN
      RAISE EXCEPTION 'Duplicate automation step key: %', v_key;
    END IF;
    v_seen_keys := array_append(v_seen_keys, v_key);

    IF v_type IS NULL OR v_type NOT IN (
      'create_case', 'collect_evidence', 'warn', 'mute', 'ban',
      'kick', 'notify', 'request_review', 'enforce', 'custom'
    ) THEN
      RAISE EXCEPTION 'Unsupported automation step type: %', COALESCE(v_type, '<null>');
    END IF;

    IF v_step ? 'config' AND jsonb_typeof(v_step->'config') <> 'object' THEN
      RAISE EXCEPTION 'Automation step config must be a JSON object when provided';
    END IF;
  END LOOP;
END;
$_$;

CREATE OR REPLACE FUNCTION %SCHEMA%.validate_broadcast_audience_filter(p_filter jsonb) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $_$
DECLARE
  v_mode text;
  v_item jsonb;
  v_value text;
  v_chat_id bigint;
  v_seen bigint[] := ARRAY[]::bigint[];
BEGIN
  IF jsonb_typeof(p_filter) <> 'object' THEN
    RAISE EXCEPTION 'Broadcast audience_filter must be a JSON object';
  END IF;

  v_mode := COALESCE(p_filter->>'mode', 'all_active');
  IF v_mode NOT IN ('all_active', 'include', 'exclude') THEN
    RAISE EXCEPTION 'Unsupported broadcast audience mode: %', v_mode;
  END IF;

  IF v_mode = 'all_active' THEN
    RETURN;
  END IF;

  IF NOT (p_filter ? 'chat_ids')
     OR jsonb_typeof(p_filter->'chat_ids') <> 'array'
     OR jsonb_array_length(p_filter->'chat_ids') = 0 THEN
    RAISE EXCEPTION 'Broadcast include/exclude audience requires a non-empty chat_ids array';
  END IF;

  FOR v_item IN SELECT value FROM jsonb_array_elements(p_filter->'chat_ids') AS items(value)
  LOOP
    IF jsonb_typeof(v_item) NOT IN ('number', 'string') THEN
      RAISE EXCEPTION 'Broadcast chat_ids entries must be numeric Telegram chat IDs';
    END IF;

    v_value := CASE
      WHEN jsonb_typeof(v_item) = 'string' THEN v_item #>> '{}'
      ELSE v_item::text
    END;

    IF v_value !~ '^-?[0-9]+$' THEN
      RAISE EXCEPTION 'Invalid Telegram chat ID in broadcast audience: %', v_value;
    END IF;

    v_chat_id := v_value::bigint;
    IF v_chat_id = ANY(v_seen) THEN
      RAISE EXCEPTION 'Duplicate chat ID in broadcast audience: %', v_chat_id;
    END IF;
    v_seen := array_append(v_seen, v_chat_id);
  END LOOP;
END;
$_$;
