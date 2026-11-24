-- The database functions that own the state transitions.
CREATE OR REPLACE FUNCTION %SCHEMA%.validate_moderation_evidence_upload() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_case_requires_evidence boolean;
  v_case_status text;
  v_chat_type text;
  v_is_forum boolean;
  v_item_count bigint;
  v_min_order integer;
  v_max_order integer;
  v_primary_order integer;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'queued' THEN
      RAISE EXCEPTION 'Evidence upload must be created in queued state';
    END IF;

    SELECT c.requires_evidence, c.status
      INTO v_case_requires_evidence, v_case_status
      FROM %SCHEMA%.moderation_cases AS c
      WHERE c.id = NEW.case_id;

    IF NOT FOUND THEN
      RAISE EXCEPTION 'Moderation case % does not exist', NEW.case_id;
    END IF;

    IF v_case_status IN ('resolved', 'dismissed', 'cancelled') THEN
      RAISE EXCEPTION 'Cannot attach evidence to a closed moderation case';
    END IF;

    -- A case-level requirement always wins, but an optional warning/mute/kick
    -- proof must remain optional unless the application explicitly marks it
    -- required for a moderation action.
    NEW.is_required := NEW.is_required OR v_case_requires_evidence;

    SELECT tc.chat_type, tc.is_forum
      INTO v_chat_type, v_is_forum
      FROM %SCHEMA%.telegram_chats AS tc
      WHERE tc.chat_id = NEW.destination_chat_id;

    IF NOT FOUND THEN
      RAISE EXCEPTION 'Evidence destination chat % is not registered', NEW.destination_chat_id;
    END IF;

    IF v_chat_type NOT IN ('group', 'supergroup', 'channel') THEN
      RAISE EXCEPTION 'Evidence destination must be a Telegram group, supergroup, or channel';
    END IF;

    IF NEW.destination_thread_id IS NOT NULL
       AND (v_chat_type <> 'supergroup' OR NOT v_is_forum) THEN
      RAISE EXCEPTION 'A destination thread requires a Telegram forum supergroup';
    END IF;
  ELSE
    IF OLD.status IN ('completed', 'partial', 'failed', 'cancelled') THEN
      RAISE EXCEPTION 'Terminal evidence uploads are immutable';
    END IF;

    IF NEW.case_id IS DISTINCT FROM OLD.case_id
       OR (
         NEW.uploaded_by_user_id IS DISTINCT FROM OLD.uploaded_by_user_id
         AND NEW.uploaded_by_user_id IS NOT NULL
       )
       OR NEW.destination_chat_id IS DISTINCT FROM OLD.destination_chat_id
       OR NEW.destination_thread_id IS DISTINCT FROM OLD.destination_thread_id
       OR NEW.is_required IS DISTINCT FROM OLD.is_required
       OR NEW.expected_item_count IS DISTINCT FROM OLD.expected_item_count
       OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
      RAISE EXCEPTION 'Evidence upload provenance is immutable except creator nullification';
    END IF;

    IF OLD.status = 'queued'
       AND NEW.status NOT IN ('queued', 'uploading', 'failed', 'cancelled') THEN
      RAISE EXCEPTION 'Invalid evidence upload transition: % -> %', OLD.status, NEW.status;
    END IF;

    IF OLD.status = 'uploading'
       AND NEW.status NOT IN ('uploading', 'completed', 'partial', 'failed', 'cancelled') THEN
      RAISE EXCEPTION 'Invalid evidence upload transition: % -> %', OLD.status, NEW.status;
    END IF;
  END IF;

  IF NEW.status = 'uploading' AND NEW.started_at IS NULL THEN
    NEW.started_at := now();
  END IF;

  IF NEW.status IN ('completed', 'partial', 'failed', 'cancelled') THEN
    SELECT count(*), min(item_order), max(item_order),
           min(item_order) FILTER (WHERE archive_message_id = NEW.primary_message_id)
      INTO v_item_count, v_min_order, v_max_order, v_primary_order
      FROM %SCHEMA%.moderation_evidence_items
      WHERE upload_id = NEW.id;

    IF NEW.status = 'completed' THEN
      IF v_item_count <> NEW.expected_item_count
         OR v_min_order <> 0 OR v_max_order <> v_item_count - 1
         OR NEW.primary_message_id IS NULL OR v_primary_order <> 0 THEN
        RAISE EXCEPTION
          'Completed upload requires exactly % sequential items and its first item as primary; found %',
          NEW.expected_item_count, v_item_count;
      END IF;
    ELSIF NEW.status = 'partial' THEN
      IF v_item_count < 1 OR v_item_count >= NEW.expected_item_count
         OR v_min_order <> 0 OR v_max_order <> v_item_count - 1
         OR NEW.primary_message_id IS NULL OR v_primary_order <> 0 THEN
        RAISE EXCEPTION 'Partial upload requires sequential archived items and its first item as primary';
      END IF;
    ELSIF NEW.status IN ('failed', 'cancelled') THEN
      IF v_item_count <> 0 OR NEW.primary_message_id IS NOT NULL THEN
        RAISE EXCEPTION 'Failed or cancelled upload cannot contain archived items; use partial when any item landed';
      END IF;
    END IF;

    NEW.finished_at := now();
  ELSE
    NEW.finished_at := NULL;
    NEW.primary_message_id := NULL;
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_appeal_ban_target() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_action_type text;
  v_action_status text;
BEGIN
  SELECT action_type, status
    INTO v_action_type, v_action_status
    FROM %SCHEMA%.moderation_actions
   WHERE id = NEW.action_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Appeal action % does not exist', NEW.action_id;
  END IF;

  IF v_action_type <> 'ban' THEN
    RAISE EXCEPTION 'Only ban actions can receive an appeal';
  END IF;

  IF TG_OP = 'INSERT' AND v_action_status <> 'active' THEN
    RAISE EXCEPTION 'A new appeal can only be submitted for an active ban';
  END IF;

  IF TG_OP = 'UPDATE'
     AND (
       NEW.action_id IS DISTINCT FROM OLD.action_id
       OR NEW.appellant_user_id IS DISTINCT FROM OLD.appellant_user_id
     ) THEN
    RAISE EXCEPTION 'Appeal action and appellant identity are immutable';
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.validate_audit_event_entity() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $_$
DECLARE
    v_exists boolean := false;
    v_numeric boolean;
BEGIN
    IF NEW.entity_id IS NULL OR btrim(NEW.entity_id) = '' THEN
        RETURN NEW;
    END IF;

    v_numeric := NEW.entity_type IN (
        'connected_chat', 'chat_settings', 'join_request', 'role_assignment',
        'promotion_request', 'moderation_case', 'moderation_action',
        'moderation_appeal', 'evidence_upload', 'evidence_item',
        'enforcement_run', 'enforcement_target', 'automation_policy',
        'automation_run', 'broadcast_campaign', 'scheduled_job_run'
    );

    IF v_numeric AND NEW.entity_id !~ '^-?[0-9]+$' THEN
        RAISE EXCEPTION
          'Audit event entity_type % requires a numeric entity_id, got %',
          NEW.entity_type, NEW.entity_id;
    END IF;

    CASE NEW.entity_type
        WHEN 'community_profile' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.community_settings WHERE singleton_key = NEW.entity_id) INTO v_exists;
        WHEN 'connected_chat' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.connected_chats WHERE chat_id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'chat_settings' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.chat_settings WHERE chat_id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'join_request' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.join_requests WHERE id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'role_definition' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.role_definitions WHERE role_key = NEW.entity_id) INTO v_exists;
        WHEN 'role_assignment' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.role_assignments WHERE id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'promotion_request' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.promotion_requests WHERE id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'moderation_case' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.moderation_cases WHERE id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'moderation_action' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.moderation_actions WHERE id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'moderation_appeal' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.moderation_appeals WHERE id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'evidence_upload' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.moderation_evidence_uploads WHERE id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'evidence_item' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.moderation_evidence_items WHERE id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'enforcement_run' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.moderation_enforcement_runs WHERE id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'enforcement_target' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.moderation_enforcement_targets WHERE id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'automation_policy' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.automation_policies WHERE id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'automation_run' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.automation_runs WHERE id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'broadcast_campaign' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.broadcast_campaigns WHERE id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'scheduled_job' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.scheduled_jobs WHERE job_key = NEW.entity_id) INTO v_exists;
        WHEN 'scheduled_job_run' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.scheduled_job_runs WHERE id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'telegram_user' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.telegram_users WHERE user_id = NEW.entity_id::bigint) INTO v_exists;
        WHEN 'retention_policy' THEN
            SELECT EXISTS (SELECT 1 FROM %SCHEMA%.retention_policies WHERE target_table = NEW.entity_id) INTO v_exists;
        ELSE
            RAISE EXCEPTION 'Unsupported audit entity_type %', NEW.entity_type;
    END CASE;

    IF NOT v_exists THEN
        RAISE EXCEPTION
          'Audit event references entity_type % with entity_id % that does not exist',
          NEW.entity_type, NEW.entity_id;
    END IF;

    RETURN NEW;
END;
$_$;
