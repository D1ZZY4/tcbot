-- The database functions that own the state transitions.
CREATE OR REPLACE FUNCTION %SCHEMA%.actor_has_permission(p_user_id bigint, p_permission_key text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
    SELECT EXISTS (
        SELECT 1
        FROM %SCHEMA%.role_assignments AS ra
        JOIN %SCHEMA%.role_permissions AS rp ON rp.role_key = ra.role_key
        WHERE ra.user_id = p_user_id
          AND ra.status = 'active'
          AND (ra.expires_at IS NULL OR ra.expires_at > now())
          AND rp.permission_key = p_permission_key
    );
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.apply_retention_policy(p_target_table text, p_limit integer DEFAULT 5000) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $_$
DECLARE
    v_policy  %SCHEMA%.retention_policies%ROWTYPE;
    v_removed integer := 0;
BEGIN
    SELECT * INTO v_policy
    FROM %SCHEMA%.retention_policies
    WHERE target_table = p_target_table;

    IF NOT FOUND THEN
        RETURN 0;
    END IF;

    IF NOT v_policy.is_enabled OR v_policy.retention_days IS NULL OR v_policy.time_column IS NULL THEN
        RETURN 0;
    END IF;

    EXECUTE format(
        'DELETE FROM %SCHEMA%.%I
          WHERE ctid IN (
              SELECT ctid FROM %SCHEMA%.%I
               WHERE %I < now() - make_interval(days => $1)
               LIMIT $2)',
        v_policy.target_table, v_policy.target_table, v_policy.time_column)
    USING v_policy.retention_days, GREATEST(p_limit, 0);

    GET DIAGNOSTICS v_removed = ROW_COUNT;

    UPDATE %SCHEMA%.retention_policies
       SET last_run_at = now(),
           last_removed = v_removed,
           updated_at = now()
     WHERE target_table = p_target_table;

    IF v_removed > 0 THEN
        INSERT INTO %SCHEMA%.audit_events (event_key, entity_type, entity_id, payload)
        VALUES ('retention.applied', 'retention_policy', v_policy.target_table,
                jsonb_build_object('removed', v_removed,
                                   'retention_days', v_policy.retention_days,
                                   'time_column', v_policy.time_column));
    END IF;

    RETURN v_removed;
END;
$_$;

CREATE OR REPLACE FUNCTION %SCHEMA%.assert_least_privilege() RETURNS TABLE(check_name text, role_name text, object_name text, severity text, detail text)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
BEGIN
    RETURN QUERY
    SELECT 'dead_delete_authority'::text,
           g.grantee::text,
           c.relname::text,
           'info'::text,
           'A delete guard trigger already blocks deletion on this table'::text
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    JOIN information_schema.role_table_grants AS g
      ON g.table_schema = n.nspname AND g.table_name = c.relname
    WHERE n.nspname = '%SCHEMA%'
      AND c.relkind = 'r'
      AND g.privilege_type = 'DELETE'
      AND g.grantee <> 'postgres'
      AND EXISTS (
          SELECT 1 FROM pg_trigger AS t
          WHERE t.tgrelid = c.oid
            AND NOT t.tgisinternal
            AND (t.tgtype & 8) > 0)

    UNION ALL
    SELECT 'sensitive_direct_access'::text,
           g.grantee::text,
           g.table_name::text,
           'warning'::text,
           'Direct access to sensitive runtime state; use the mtproto_state_ functions instead'::text
    FROM information_schema.role_table_grants AS g
    WHERE g.table_schema = '%SCHEMA%'
      AND g.table_name = 'mtproto_state'
      AND g.privilege_type IN ('SELECT', 'UPDATE', 'DELETE', 'INSERT')
      AND g.grantee <> 'postgres'

    UNION ALL
    SELECT 'rls_bypass_role'::text,
           r.rolname::text,
           'public schema'::text,
           'warning'::text,
           'Role bypasses row level security and can read every table'::text
    FROM pg_roles AS r
    WHERE r.rolbypassrls
      AND r.rolname NOT IN ('postgres', 'supabase_admin')

    UNION ALL
    SELECT 'object_owner'::text,
           pg_get_userbyid(c.relowner)::text,
           c.relname::text,
           'info'::text,
           'Owner can alter or disable the triggers that protect this object'::text
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = '%SCHEMA%'
      AND c.relkind IN ('r', 'v')
      AND pg_get_userbyid(c.relowner) NOT IN ('postgres', 'supabase_admin')

    ORDER BY 1, 2, 3;
END;
$$;

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

CREATE OR REPLACE FUNCTION %SCHEMA%.audit_scheduler_drift() RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog, public, cron'
    AS $$
DECLARE
    v_total   integer;
    v_missing integer;
BEGIN
    SELECT count(*),
           count(*) FILTER (WHERE in_registry AND NOT registered_in_cron)
      INTO v_total, v_missing
    FROM %SCHEMA%.scheduler_drift_report();

    IF v_missing > 0 THEN
        INSERT INTO %SCHEMA%.audit_events (event_key, entity_type, entity_id, payload)
        VALUES ('scheduler.drift.detected', 'scheduled_job', 'scheduler.drift',
                jsonb_build_object('missing_in_cron', v_missing,
                                   'total', v_total));
    END IF;

    RETURN jsonb_build_object('drift_rows', v_total,
                              'missing_in_cron', v_missing);
END;
$$;

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

CREATE OR REPLACE FUNCTION %SCHEMA%.ensure_connected_chat_settings() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  INSERT INTO %SCHEMA%.chat_settings (chat_id)
  VALUES (NEW.chat_id)
  ON CONFLICT (chat_id) DO NOTHING;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.ensure_published_rule_acknowledgement() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
  v_version_status text;
  v_rule_set_active boolean;
BEGIN
  SELECT rsv.status, rs.is_active
    INTO v_version_status, v_rule_set_active
    FROM %SCHEMA%.rule_set_versions AS rsv
    JOIN %SCHEMA%.rule_sets AS rs ON rs.id = rsv.rule_set_id
    WHERE rsv.id = NEW.rule_set_version_id
    FOR KEY SHARE OF rsv, rs;

  IF NOT FOUND
     OR v_version_status IS DISTINCT FROM 'published'
     OR NOT v_rule_set_active THEN
    RAISE EXCEPTION 'Only active rule sets with a currently published version can be acknowledged';
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.expire_due_moderation_actions() RETURNS bigint
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_expired_count bigint;
BEGIN
  UPDATE %SCHEMA%.moderation_actions
     SET status = 'expired'
   WHERE action_type IN ('ban', 'mute')
     AND status = 'active'
     AND expires_at IS NOT NULL
     AND expires_at <= now();

  GET DIAGNOSTICS v_expired_count = ROW_COUNT;
  RETURN v_expired_count;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.expire_due_moderation_actions_and_queue_revokes() RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog, public'
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

CREATE OR REPLACE FUNCTION %SCHEMA%.expire_due_role_assignments() RETURNS bigint
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_expired_count bigint;
BEGIN
  UPDATE %SCHEMA%.role_assignments
     SET status = 'expired'
   WHERE status = 'active'
     AND expires_at IS NOT NULL
     AND expires_at <= now();

  GET DIAGNOSTICS v_expired_count = ROW_COUNT;
  RETURN v_expired_count;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.expire_due_role_assignments_and_audit() RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog, public'
    AS $$
DECLARE
    v_expired integer;
    v_ids     bigint[];
    v_first   bigint;
BEGIN
    SELECT array_agg(id) INTO v_ids
    FROM %SCHEMA%.role_assignments
    WHERE status = 'active'
      AND expires_at IS NOT NULL
      AND expires_at <= now();

    v_expired := %SCHEMA%.expire_due_role_assignments();

    IF v_expired > 0 THEN
        v_first := v_ids[1];
        INSERT INTO %SCHEMA%.audit_events (event_key, entity_type, entity_id, payload)
        VALUES ('role.expired', 'role_assignment', v_first::text,
                jsonb_build_object('expired_count', v_expired,
                                   'expired_ids', to_jsonb(v_ids)));
    END IF;

    RETURN jsonb_build_object('expired_role_assignments', v_expired);
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

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_community_settings_singleton() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'The global community settings row cannot be deleted';
  END IF;

  IF NEW.singleton_key IS DISTINCT FROM 'global' THEN
    RAISE EXCEPTION 'Only the global community settings singleton is permitted';
  END IF;

  IF TG_OP = 'UPDATE'
     AND NEW.singleton_key IS DISTINCT FROM OLD.singleton_key THEN
    RAISE EXCEPTION 'The community settings singleton identity is immutable';
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_join_request_lifecycle() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_repoint_source bigint := NULLIF(
        current_setting('tcbot.chat_repoint_source', true), ''
    )::bigint;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'pending' OR NEW.resolved_at IS NOT NULL OR NEW.resolved_by_user_id IS NOT NULL THEN
      RAISE EXCEPTION 'Join requests must be created pending and unresolved';
    END IF;
    RETURN NEW;
  END IF;
  -- * The request belongs to the chat it was filed for, so it follows
  -- * the chat when the group moves. Only the repoint function performs
  -- * that move.
  IF NEW.chat_id IS DISTINCT FROM OLD.chat_id
     AND NOT (v_repoint_source IS NOT NULL AND OLD.chat_id = v_repoint_source) THEN
    RAISE EXCEPTION 'Join request identity and request facts are immutable';
  END IF;
  IF NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
     OR NEW.request_message_id IS DISTINCT FROM OLD.request_message_id
     OR NEW.requested_at IS DISTINCT FROM OLD.requested_at THEN
    RAISE EXCEPTION 'Join request identity and request facts are immutable';
  END IF;
  IF OLD.status <> 'pending' THEN
    IF NEW.status IS DISTINCT FROM OLD.status
       OR NEW.resolved_at IS DISTINCT FROM OLD.resolved_at
       OR NEW.decision_note IS DISTINCT FROM OLD.decision_note
       OR (NEW.resolved_by_user_id IS DISTINCT FROM OLD.resolved_by_user_id
           AND NEW.resolved_by_user_id IS NOT NULL) THEN
      RAISE EXCEPTION 'Resolved join request decisions are immutable';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.status NOT IN ('pending','approved','rejected','cancelled') THEN
    RAISE EXCEPTION 'Invalid join request transition: % -> %', OLD.status, NEW.status;
  END IF;
  IF NEW.status = 'pending' THEN
    IF NEW.resolved_by_user_id IS NOT NULL OR NEW.resolved_at IS NOT NULL THEN
      RAISE EXCEPTION 'Pending join requests cannot have resolution metadata';
    END IF;
  ELSE
    NEW.resolved_at := COALESCE(NEW.resolved_at, now());
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.repoint_chat_records(
    p_old_chat_id bigint,
    p_new_chat_id bigint
) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog, public'
    AS $$
DECLARE
    v_actions   integer;
    v_members   integer;
    v_dropped_members integer;
    v_requests  integer;
    v_settings  integer;
    v_was_active boolean;
BEGIN
    IF p_old_chat_id IS NULL OR p_new_chat_id IS NULL
       OR p_old_chat_id = p_new_chat_id THEN
        RAISE EXCEPTION 'A chat repoint needs two different chat ids';
    END IF;

    SELECT is_active INTO v_was_active
      FROM %SCHEMA%.connected_chats
     WHERE chat_id = p_old_chat_id;

    -- * The new chat inherits the identity of the old one, so the group
    -- * keeps its title, its type, and its forum flag.
    INSERT INTO %SCHEMA%.telegram_chats (
        chat_id, chat_type, title, username, description, is_forum,
        created_at, updated_at
    )
    SELECT p_new_chat_id, c.chat_type, c.title, c.username, c.description,
           c.is_forum, c.created_at, now()
      FROM %SCHEMA%.telegram_chats AS c
     WHERE c.chat_id = p_old_chat_id
    ON CONFLICT (chat_id) DO UPDATE
        SET chat_type = EXCLUDED.chat_type,
            title = COALESCE(EXCLUDED.title, %SCHEMA%.telegram_chats.title),
            username = COALESCE(EXCLUDED.username, %SCHEMA%.telegram_chats.username),
            description = COALESCE(
                EXCLUDED.description, %SCHEMA%.telegram_chats.description
            ),
            is_forum = %SCHEMA%.telegram_chats.is_forum OR EXCLUDED.is_forum,
            updated_at = now();

    -- * The configuration of the group follows it.
    INSERT INTO %SCHEMA%.chat_settings (
        chat_id, locale, timezone, settings, created_at, updated_at
    )
    SELECT p_new_chat_id, s.locale, s.timezone, s.settings, s.created_at, now()
      FROM %SCHEMA%.chat_settings AS s
     WHERE s.chat_id = p_old_chat_id
    ON CONFLICT (chat_id) DO UPDATE
        SET locale = COALESCE(%SCHEMA%.chat_settings.locale, EXCLUDED.locale),
            timezone = COALESCE(%SCHEMA%.chat_settings.timezone, EXCLUDED.timezone),
            settings = %SCHEMA%.chat_settings.settings || EXCLUDED.settings,
            updated_at = now();
    GET DIAGNOSTICS v_settings = ROW_COUNT;

    DELETE FROM %SCHEMA%.chat_settings WHERE chat_id = p_old_chat_id;

    -- * The registry follows the group. The old chat stays known but
    -- * inactive, so the history that refers to it stays readable.
    UPDATE %SCHEMA%.connected_chats
       SET is_active = false
     WHERE chat_id = p_old_chat_id;

    INSERT INTO %SCHEMA%.connected_chats (
        chat_id, added_by_user_id, added_at, is_active
    )
    SELECT p_new_chat_id, g.added_by_user_id, g.added_at, true
      FROM %SCHEMA%.connected_chats AS g
     WHERE g.chat_id = p_old_chat_id
    ON CONFLICT (chat_id) DO UPDATE
        SET is_active = true,
            added_by_user_id = COALESCE(
                %SCHEMA%.connected_chats.added_by_user_id, EXCLUDED.added_by_user_id
            ),
            added_at = LEAST(%SCHEMA%.connected_chats.added_at, EXCLUDED.added_at);

    -- * The membership of the group follows it. A member the new chat
    -- * already knows keeps the state of the new chat.
    UPDATE %SCHEMA%.chat_members AS m
       SET chat_id = p_new_chat_id, updated_at = now()
     WHERE m.chat_id = p_old_chat_id
       AND NOT EXISTS (
           SELECT 1 FROM %SCHEMA%.chat_members AS n
            WHERE n.chat_id = p_new_chat_id AND n.user_id = m.user_id
       );
    GET DIAGNOSTICS v_members = ROW_COUNT;
    DELETE FROM %SCHEMA%.chat_members WHERE chat_id = p_old_chat_id;
    GET DIAGNOSTICS v_dropped_members = ROW_COUNT;

    -- * The open request of the group follows it. A group can only have
    -- * one open request, so a request that cannot move because the new
    -- * chat already has one is cancelled.
    UPDATE %SCHEMA%.join_requests
       SET status = 'cancelled', resolved_at = now()
     WHERE chat_id = p_old_chat_id
       AND status = 'pending'
       AND EXISTS (
           SELECT 1 FROM %SCHEMA%.join_requests AS r
            WHERE r.chat_id = p_new_chat_id AND r.status = 'pending'
       );

    -- * The decisions of the group follow it. The guard lets the chat
    -- * move because this transaction is the repoint.
    PERFORM set_config('tcbot.chat_repoint_source', p_old_chat_id::text, true);

    UPDATE %SCHEMA%.moderation_actions
       SET chat_id = CASE
               WHEN chat_id = p_old_chat_id THEN p_new_chat_id
               ELSE chat_id
           END,
           origin_chat_id = CASE
               WHEN origin_chat_id = p_old_chat_id THEN p_new_chat_id
               ELSE origin_chat_id
           END
     WHERE chat_id = p_old_chat_id OR origin_chat_id = p_old_chat_id;
    GET DIAGNOSTICS v_actions = ROW_COUNT;

    UPDATE %SCHEMA%.join_requests
       SET chat_id = p_new_chat_id
     WHERE chat_id = p_old_chat_id AND status = 'pending';
    GET DIAGNOSTICS v_requests = ROW_COUNT;

    -- * The context of a rule violation follows the group it happened in.
    UPDATE %SCHEMA%.moderation_case_rules
       SET context_chat_id = p_new_chat_id
     WHERE context_chat_id = p_old_chat_id;

    IF v_was_active THEN
        INSERT INTO %SCHEMA%.audit_events (
            event_key, entity_type, entity_id, payload
        )
        VALUES (
            'group.connection.migrated', 'connected_chat', p_new_chat_id::text,
            jsonb_build_object(
                'old_chat_id', p_old_chat_id,
                'new_chat_id', p_new_chat_id,
                'moved_decisions', v_actions
            )
        );
    END IF;

    RETURN jsonb_build_object(
        'old_chat_id', p_old_chat_id,
        'new_chat_id', p_new_chat_id,
        'was_active', COALESCE(v_was_active, false),
        'moved_decisions', v_actions,
        'moved_members', v_members,
        'dropped_members', v_dropped_members,
        'moved_requests', v_requests,
        'moved_settings', v_settings
    );
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
  IF OLD.status IN ('revoked', 'expired', 'superseded')
     AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'Terminal moderation action status cannot be changed';
  END IF;
  IF OLD.status = 'active'
     AND NEW.status NOT IN ('active', 'revoked', 'expired', 'superseded') THEN
    RAISE EXCEPTION 'Invalid moderation action transition: % -> %', OLD.status, NEW.status;
  END IF;
  IF OLD.status = 'completed' AND NEW.status NOT IN ('completed', 'revoked') THEN
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

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_promotion_request_lifecycle() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'pending' OR NEW.resolved_at IS NOT NULL OR NEW.resolved_by_user_id IS NOT NULL THEN
      RAISE EXCEPTION 'Promotion requests must be created pending and unresolved';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.request_id IS DISTINCT FROM OLD.request_id
     OR NEW.target_user_id IS DISTINCT FROM OLD.target_user_id
     OR NEW.requested_role_key IS DISTINCT FROM OLD.requested_role_key
     OR NEW.requested_by_user_id IS DISTINCT FROM OLD.requested_by_user_id
     OR NEW.requested_at IS DISTINCT FROM OLD.requested_at THEN
    RAISE EXCEPTION 'Promotion request identity and request facts are immutable';
  END IF;
  IF OLD.status <> 'pending' THEN
    IF NEW.status IS DISTINCT FROM OLD.status
       OR NEW.resolved_at IS DISTINCT FROM OLD.resolved_at
       OR NEW.decision_note IS DISTINCT FROM OLD.decision_note
       OR (NEW.resolved_by_user_id IS DISTINCT FROM OLD.resolved_by_user_id
           AND NEW.resolved_by_user_id IS NOT NULL) THEN
      RAISE EXCEPTION 'Resolved promotion request decisions are immutable';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.status NOT IN ('pending','approved','rejected','cancelled') THEN
    RAISE EXCEPTION 'Invalid promotion request transition: % -> %', OLD.status, NEW.status;
  END IF;
  IF NEW.status = 'pending' THEN
    IF NEW.resolved_by_user_id IS NOT NULL OR NEW.resolved_at IS NOT NULL THEN
      RAISE EXCEPTION 'Pending promotion requests cannot have resolution metadata';
    END IF;
  ELSE
    NEW.resolved_at := COALESCE(NEW.resolved_at, now());
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_role_assignment_update() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  IF NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.role_key IS DISTINCT FROM OLD.role_key
     OR NEW.assigned_at IS DISTINCT FROM OLD.assigned_at
     OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
     OR (NEW.assigned_by_user_id IS DISTINCT FROM OLD.assigned_by_user_id
         AND NEW.assigned_by_user_id IS NOT NULL) THEN
    RAISE EXCEPTION 'Role assignment facts are immutable; only actor nullification is permitted';
  END IF;
  IF OLD.status IN ('revoked', 'expired') AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'Terminal role assignment status cannot be changed';
  END IF;
  IF OLD.status = 'active' AND NEW.status NOT IN ('active', 'revoked', 'expired') THEN
    RAISE EXCEPTION 'Invalid role assignment transition: % -> %', OLD.status, NEW.status;
  END IF;
  IF NEW.status = 'revoked' THEN
    NEW.revoked_at := COALESCE(OLD.revoked_at, NEW.revoked_at, now());
  END IF;
  IF NEW.status = 'expired' AND (NEW.expires_at IS NULL OR NEW.expires_at > now()) THEN
    RAISE EXCEPTION 'Only role assignments whose expiry time has passed can become expired';
  END IF;
  IF OLD.status = 'revoked' THEN
    IF NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
      RAISE EXCEPTION 'Role revocation timestamp is immutable';
    END IF;
    IF NEW.revoked_by_user_id IS DISTINCT FROM OLD.revoked_by_user_id
       AND NEW.revoked_by_user_id IS NOT NULL THEN
      RAISE EXCEPTION 'Role revocation actor is immutable; only FK-driven nullification is permitted';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_rule_acknowledgement_history() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  RAISE EXCEPTION 'Rule acknowledgements are immutable historical records; % is not allowed', TG_OP;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_rule_item_draft_only() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    version_status text;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status
        INTO version_status
        FROM %SCHEMA%.rule_set_versions
        WHERE id = OLD.rule_set_version_id
        FOR KEY SHARE;

        IF version_status IS DISTINCT FROM 'draft' THEN
            RAISE EXCEPTION 'Rule items belonging to non-draft versions are immutable';
        END IF;
    END IF;

    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status
        INTO version_status
        FROM %SCHEMA%.rule_set_versions
        WHERE id = NEW.rule_set_version_id
        FOR KEY SHARE;

        IF version_status IS DISTINCT FROM 'draft' THEN
            RAISE EXCEPTION 'Rule items can only be written to draft versions';
        END IF;
        RETURN NEW;
    END IF;

    RETURN OLD;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_rule_set_identity() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  IF NEW.scope_type IS DISTINCT FROM OLD.scope_type
     OR NEW.chat_id IS DISTINCT FROM OLD.chat_id
     OR NEW.rule_set_key IS DISTINCT FROM OLD.rule_set_key
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR (NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
         AND NEW.created_by_user_id IS NOT NULL) THEN
    RAISE EXCEPTION 'Rule-set scope and identity are immutable; only creator nullification is permitted';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_rule_set_version_changes() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
  v_rule_set_active boolean;
  v_item_count bigint;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'draft'
       OR NEW.published_by_user_id IS NOT NULL
       OR NEW.published_at IS NOT NULL THEN
      RAISE EXCEPTION
        'New rule-set versions must start as unpublished drafts';
    END IF;

    RETURN NEW;
  END IF;

  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Only draft rule-set versions may be deleted';
    END IF;
    RETURN OLD;
  END IF;

  IF NEW.rule_set_id IS DISTINCT FROM OLD.rule_set_id
     OR NEW.version_number IS DISTINCT FROM OLD.version_number
     OR NEW.locale IS DISTINCT FROM OLD.locale THEN
    RAISE EXCEPTION 'Rule-set identity, version number, and locale are immutable';
  END IF;

  IF OLD.status <> 'draft' THEN
    IF (
         NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
         AND NEW.created_by_user_id IS NOT NULL
       )
       OR NEW.published_by_user_id IS DISTINCT FROM OLD.published_by_user_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.published_at IS DISTINCT FROM OLD.published_at
       OR NEW.change_summary IS DISTINCT FROM OLD.change_summary THEN
      RAISE EXCEPTION 'Published rule-set version metadata is immutable';
    END IF;

    IF NOT (
      (OLD.status = 'published' AND NEW.status IN ('published', 'superseded', 'archived'))
      OR (OLD.status = 'superseded' AND NEW.status IN ('superseded', 'archived'))
      OR (OLD.status = 'archived' AND NEW.status = 'archived')
    ) THEN
      RAISE EXCEPTION 'Invalid rule-set version lifecycle transition: % -> %',
        OLD.status, NEW.status;
    END IF;
  ELSE
    IF NEW.status NOT IN ('draft', 'published', 'archived') THEN
      RAISE EXCEPTION 'Invalid rule-set version lifecycle transition: % -> %',
        OLD.status, NEW.status;
    END IF;

    IF NEW.status = 'published' THEN
      SELECT rs.is_active INTO v_rule_set_active
      FROM %SCHEMA%.rule_sets AS rs
      WHERE rs.id = NEW.rule_set_id
      FOR KEY SHARE;

      IF NOT FOUND OR NOT v_rule_set_active THEN
        RAISE EXCEPTION 'Cannot publish a version for an inactive or missing rule set';
      END IF;

      SELECT count(*) INTO v_item_count
      FROM %SCHEMA%.rule_items AS ri
      WHERE ri.rule_set_version_id = OLD.id;

      IF v_item_count = 0 THEN
        RAISE EXCEPTION 'A rule-set version must contain at least one rule item before publication';
      END IF;
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_scheduled_job_run() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'running' OR NEW.finished_at IS NOT NULL THEN
            RAISE EXCEPTION 'Scheduled job runs must start in the running state';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF OLD.started_at < now() - make_interval(days => %SCHEMA%.retention_window_days('scheduled_job_runs')) THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION
          'Scheduled job runs are append-only; the row records the execution history';
    END IF;

    IF NEW.job_key IS DISTINCT FROM OLD.job_key
       OR NEW.run_key IS DISTINCT FROM OLD.run_key
       OR NEW.started_at IS DISTINCT FROM OLD.started_at
       OR NEW.triggered_by IS DISTINCT FROM OLD.triggered_by THEN
        RAISE EXCEPTION 'Scheduled job run identity is immutable';
    END IF;

    IF OLD.status <> 'running' THEN
        RAISE EXCEPTION 'A finished scheduled job run cannot be reopened';
    END IF;

    IF NEW.status NOT IN ('success', 'failed', 'skipped') THEN
        RAISE EXCEPTION 'Invalid scheduled job run transition: % -> %', OLD.status, NEW.status;
    END IF;

    NEW.finished_at := COALESCE(NEW.finished_at, now());
    NEW.duration_ms := COALESCE(
        NEW.duration_ms,
        %SCHEMA%.safe_duration_ms(NEW.finished_at - NEW.started_at));

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_system_role_definition() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_renameable constant text[] := ARRAY['founder','owner','admin','developer','tester','moderator'];
BEGIN
    IF OLD.is_system THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'System role definitions cannot be deleted';
        END IF;

        IF NEW.is_system IS DISTINCT FROM OLD.is_system THEN
            RAISE EXCEPTION 'System role identity cannot be changed';
        END IF;

        IF NEW.role_key IS DISTINCT FROM OLD.role_key THEN
            IF coalesce(current_setting('tcbot.allow_system_role_rename', true), 'off') <> 'on' THEN
                RAISE EXCEPTION 'System role identity cannot be changed';
            END IF;

            IF NOT (OLD.role_key = ANY (v_renameable)) THEN
                RAISE EXCEPTION 'Role % is not eligible for a rename', OLD.role_key;
            END IF;

            IF EXISTS (SELECT 1 FROM %SCHEMA%.role_definitions WHERE role_key = NEW.role_key) THEN
                RAISE EXCEPTION 'Target role key % already exists', NEW.role_key;
            END IF;
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_telegram_chat_type_change() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  IF NEW.chat_type IS DISTINCT FROM OLD.chat_type
     AND NEW.chat_type NOT IN ('group', 'supergroup')
     AND EXISTS (
       SELECT 1 FROM %SCHEMA%.connected_chats AS cc WHERE cc.chat_id = OLD.chat_id
     ) THEN
    RAISE EXCEPTION 'A connected community chat cannot be converted to a non-group chat type';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.mtproto_state_claim(p_id text, p_owner text, p_ttl_seconds integer DEFAULT 60) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_claimed boolean;
BEGIN
    WITH claimed AS (
        UPDATE %SCHEMA%.mtproto_state AS s
           SET owner = p_owner,
               expires_at = extract(epoch FROM clock_timestamp())::bigint + p_ttl_seconds
         WHERE s.id = p_id
           AND (s.owner IS NULL OR s.expires_at IS NULL
                OR s.expires_at <= extract(epoch FROM clock_timestamp())::bigint)
        RETURNING 1
    )
    SELECT EXISTS (SELECT 1 FROM claimed) INTO v_claimed;

    RETURN v_claimed;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.mtproto_state_delete(p_id text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_affected integer;
BEGIN
    DELETE FROM %SCHEMA%.mtproto_state WHERE id = p_id;
    GET DIAGNOSTICS v_affected = ROW_COUNT;
    RETURN v_affected > 0;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.mtproto_state_find_by_phone(p_phone_number text) RETURNS TABLE(id text, value bytea, access_hash bigint, type text, usernames text[], phone_number text, updated_on bigint, expires_at bigint, pts integer, qts integer, date integer, seq integer, owner text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    RETURN QUERY
    SELECT s.id, s.value, s.access_hash, s.type, s.usernames, s.phone_number,
           s.updated_on, s.expires_at, s.pts, s.qts, s."date", s.seq, s.owner
    FROM %SCHEMA%.mtproto_state AS s
    WHERE s.phone_number = p_phone_number;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.mtproto_state_find_by_username(p_username text) RETURNS TABLE(id text, value bytea, access_hash bigint, type text, usernames text[], phone_number text, updated_on bigint, expires_at bigint, pts integer, qts integer, date integer, seq integer, owner text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    RETURN QUERY
    SELECT s.id, s.value, s.access_hash, s.type, s.usernames, s.phone_number,
           s.updated_on, s.expires_at, s.pts, s.qts, s."date", s.seq, s.owner
    FROM %SCHEMA%.mtproto_state AS s
    WHERE lower(p_username) = ANY (SELECT lower(u) FROM unnest(s.usernames) AS u);
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.mtproto_state_get(p_id text) RETURNS TABLE(id text, value bytea, access_hash bigint, type text, usernames text[], phone_number text, updated_on bigint, expires_at bigint, pts integer, qts integer, date integer, seq integer, owner text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    RETURN QUERY
    SELECT s.id, s.value, s.access_hash, s.type, s.usernames, s.phone_number,
           s.updated_on, s.expires_at, s.pts, s.qts, s."date", s.seq, s.owner
    FROM %SCHEMA%.mtproto_state AS s
    WHERE s.id = p_id;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.mtproto_state_put(p_id text, p_value bytea, p_access_hash bigint, p_type text, p_usernames text[], p_phone_number text, p_updated_on bigint, p_expires_at bigint, p_pts integer, p_qts integer, p_date integer, p_seq integer, p_owner text) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    INSERT INTO %SCHEMA%.mtproto_state
        (id, value, access_hash, type, usernames, phone_number,
         updated_on, expires_at, pts, qts, "date", seq, owner)
    VALUES
        (p_id, p_value, p_access_hash, p_type, p_usernames, p_phone_number,
         p_updated_on, p_expires_at, p_pts, p_qts, p_date, p_seq, p_owner)
    ON CONFLICT (id) DO UPDATE SET
        value        = EXCLUDED.value,
        access_hash  = EXCLUDED.access_hash,
        type         = EXCLUDED.type,
        usernames    = EXCLUDED.usernames,
        phone_number = EXCLUDED.phone_number,
        updated_on   = EXCLUDED.updated_on,
        expires_at   = EXCLUDED.expires_at,
        pts          = EXCLUDED.pts,
        qts          = EXCLUDED.qts,
        "date"       = EXCLUDED."date",
        seq          = EXCLUDED.seq,
        owner        = EXCLUDED.owner;
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
    IF NOT EXISTS (
      SELECT 1 FROM %SCHEMA%.connected_chats AS cc
      WHERE cc.chat_id = NEW.chat_id AND cc.is_active
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

  UPDATE %SCHEMA%.moderation_actions AS a
     SET status = 'expired'
   WHERE a.scope_type = NEW.scope_type
     AND a.chat_id IS NOT DISTINCT FROM NEW.chat_id
     AND a.target_user_id = NEW.target_user_id
     AND a.action_type = NEW.action_type
     AND a.status = 'active'
     AND a.expires_at IS NOT NULL
     AND a.expires_at <= NEW.created_at;

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

    IF NOT EXISTS (
      SELECT 1 FROM %SCHEMA%.connected_chats AS cc
      WHERE cc.chat_id = NEW.chat_id AND cc.is_active
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
      WHERE cc.chat_id = NEW.chat_id AND cc.is_active
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

CREATE OR REPLACE FUNCTION %SCHEMA%.prepare_role_assignment() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  IF NEW.status <> 'active' OR NEW.revoked_at IS NOT NULL OR NEW.revoked_by_user_id IS NOT NULL
     OR (NEW.expires_at IS NOT NULL AND NEW.expires_at <= NEW.assigned_at) THEN
    RAISE EXCEPTION 'New role assignments must start active, unrevoked, and not already expired';
  END IF;
  UPDATE %SCHEMA%.role_assignments AS ra
     SET status = 'expired'
   WHERE ra.user_id = NEW.user_id
     AND ra.status = 'active'
     AND ra.expires_at IS NOT NULL
     AND ra.expires_at <= NEW.assigned_at;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.prevent_historical_record_delete() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
    BEGIN
      RAISE EXCEPTION 'Historical record in % is append-only; use its lifecycle state instead of deleting it', TG_TABLE_NAME;
    END;
    $$;

CREATE OR REPLACE FUNCTION %SCHEMA%.process_user_erasure(p_erasure_id bigint) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    v_req       %SCHEMA%.telegram_user_erasures%ROWTYPE;
    v_affected  jsonb := '{}'::jsonb;
    v_count     integer;
    v_action_id bigint;
BEGIN
    SELECT * INTO v_req
    FROM %SCHEMA%.telegram_user_erasures
    WHERE id = p_erasure_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Erasure request % does not exist', p_erasure_id;
    END IF;

    IF v_req.status <> 'pending' THEN
        RAISE EXCEPTION 'Erasure request % is %', p_erasure_id, v_req.status;
    END IF;

    UPDATE %SCHEMA%.telegram_user_erasures
       SET status = 'processing'
     WHERE id = p_erasure_id;

    UPDATE %SCHEMA%.telegram_users
       SET username       = NULL,
           first_name     = NULL,
           last_name      = NULL,
           language_code  = NULL,
           is_premium     = false,
           erased_at      = now(),
           erasure_reason = v_req.reason,
           updated_at      = now()
     WHERE user_id = v_req.user_id;

    DELETE FROM %SCHEMA%.chat_members WHERE user_id = v_req.user_id;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_affected := jsonb_set(v_affected, '{chat_members}', to_jsonb(v_count), true);

    DELETE FROM %SCHEMA%.user_settings WHERE user_id = v_req.user_id;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_affected := jsonb_set(v_affected, '{user_settings}', to_jsonb(v_count), true);

    UPDATE %SCHEMA%.role_assignments
       SET status = 'revoked',
           revoked_at = now()
     WHERE user_id = v_req.user_id AND status = 'active';
    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_affected := jsonb_set(v_affected, '{role_assignments_revoked}', to_jsonb(v_count), true);

    FOR v_action_id IN
        UPDATE %SCHEMA%.moderation_actions
           SET status = 'revoked',
               revoked_at = now()
         WHERE target_user_id = v_req.user_id
           AND status = 'active'
        RETURNING id
    LOOP
        INSERT INTO %SCHEMA%.moderation_enforcement_runs
            (action_id, operation, idempotency_key, requested_by_user_id, status)
        VALUES
            (v_action_id, 'revoke',
             format('moderation:%s:revoke:erasure:v1', v_action_id),
             v_req.processed_by_user_id, 'queued')
        ON CONFLICT (idempotency_key) DO NOTHING;

        INSERT INTO %SCHEMA%.moderation_enforcement_targets (run_id, chat_id)
        SELECT r.id, cc.chat_id
        FROM %SCHEMA%.moderation_enforcement_runs AS r
        JOIN %SCHEMA%.connected_chats AS cc ON cc.is_active
        WHERE r.idempotency_key = format('moderation:%s:revoke:erasure:v1', v_action_id)
        ON CONFLICT (run_id, chat_id) DO NOTHING;
    END LOOP;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_affected := jsonb_set(v_affected, '{moderation_actions_revoked}', to_jsonb(v_count), true);

    UPDATE %SCHEMA%.telegram_user_erasures
       SET status = 'completed',
           processed_at = now(),
           affected = v_affected
     WHERE id = p_erasure_id;

    INSERT INTO %SCHEMA%.audit_events (event_key, entity_type, entity_id, subject_user_id, payload)
    VALUES ('telegram.user.erased', 'telegram_user', v_req.user_id::text, v_req.user_id,
            jsonb_build_object('reason', v_req.reason,
                               'source', v_req.source,
                               'affected', v_affected,
                               'erasure_id', p_erasure_id));

    RETURN v_affected;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.promotion_requests_approve(p_request_id text, p_actor_user_id bigint, p_decision_note text DEFAULT NULL::text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    v_request    %SCHEMA%.promotion_requests%ROWTYPE;
    v_assignment bigint;
BEGIN
    SELECT * INTO v_request
    FROM %SCHEMA%.promotion_requests
    WHERE request_id = p_request_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Promotion request % does not exist', p_request_id;
    END IF;

    IF v_request.status <> 'pending' THEN
        RAISE EXCEPTION 'Promotion request % is already %', p_request_id, v_request.status;
    END IF;

    IF NOT %SCHEMA%.actor_has_permission(p_actor_user_id, 'roles.review_promotion_requests') THEN
        RAISE EXCEPTION 'Actor % cannot review promotion requests', p_actor_user_id;
    END IF;

    IF p_actor_user_id = v_request.target_user_id THEN
        RAISE EXCEPTION 'A promotion request cannot be approved by its own target';
    END IF;

    IF v_request.requested_role_key = 'owner' THEN
        RAISE EXCEPTION 'The owner role must be granted through ownership transfer, not a promotion request';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM %SCHEMA%.role_definitions WHERE role_key = v_request.requested_role_key) THEN
        RAISE EXCEPTION 'Unknown role %', v_request.requested_role_key;
    END IF;

    IF EXISTS (
        SELECT 1 FROM %SCHEMA%.role_assignments
        WHERE user_id = v_request.target_user_id AND status = 'active'
    ) THEN
        RAISE EXCEPTION 'Target % already holds an active role', v_request.target_user_id;
    END IF;

    UPDATE %SCHEMA%.promotion_requests
       SET status = 'approved',
           resolved_at = now(),
           resolved_by_user_id = p_actor_user_id,
           decision_note = p_decision_note
     WHERE request_id = p_request_id;

    INSERT INTO %SCHEMA%.role_assignments
        (user_id, role_key, assigned_by_user_id, status)
    VALUES
        (v_request.target_user_id, v_request.requested_role_key, p_actor_user_id, 'active')
    RETURNING id INTO v_assignment;

    INSERT INTO %SCHEMA%.audit_events (event_key, entity_type, entity_id, subject_user_id, actor_user_id, payload)
    VALUES ('role.promoted', 'role_assignment', v_assignment::text, v_request.target_user_id, p_actor_user_id,
            jsonb_build_object('request_id', p_request_id,
                               'role_key', v_request.requested_role_key,
                               'decision_note', p_decision_note));

    RETURN v_assignment;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.promotion_requests_reject(p_request_id text, p_actor_user_id bigint, p_decision_note text DEFAULT NULL::text) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    v_request %SCHEMA%.promotion_requests%ROWTYPE;
BEGIN
    SELECT * INTO v_request
    FROM %SCHEMA%.promotion_requests
    WHERE request_id = p_request_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Promotion request % does not exist', p_request_id;
    END IF;

    IF v_request.status <> 'pending' THEN
        RAISE EXCEPTION 'Promotion request % is already %', p_request_id, v_request.status;
    END IF;

    IF NOT %SCHEMA%.actor_has_permission(p_actor_user_id, 'roles.review_promotion_requests') THEN
        RAISE EXCEPTION 'Actor % cannot review promotion requests', p_actor_user_id;
    END IF;

    IF p_actor_user_id = v_request.target_user_id THEN
        RAISE EXCEPTION 'A promotion request cannot be rejected by its own target';
    END IF;

    UPDATE %SCHEMA%.promotion_requests
       SET status = 'rejected',
           resolved_at = now(),
           resolved_by_user_id = p_actor_user_id,
           decision_note = p_decision_note
     WHERE request_id = p_request_id;

    INSERT INTO %SCHEMA%.audit_events (event_key, entity_type, entity_id, subject_user_id, actor_user_id, payload)
    VALUES ('role.promotion.rejected', 'promotion_request', p_request_id, v_request.target_user_id, p_actor_user_id,
            jsonb_build_object('role_key', v_request.requested_role_key,
                               'decision_note', p_decision_note));
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.prune_expired_mtproto_state() RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    v_removed integer := 0;
BEGIN
    DELETE FROM %SCHEMA%.mtproto_state
    WHERE expires_at IS NOT NULL
      AND expires_at <= extract(epoch FROM clock_timestamp())::bigint;

    GET DIAGNOSTICS v_removed = ROW_COUNT;

    IF v_removed > 0 THEN
        INSERT INTO %SCHEMA%.audit_events (event_key, entity_type, entity_id, payload)
        VALUES ('retention.applied', 'retention_policy', 'mtproto_state',
                jsonb_build_object('removed', v_removed,
                                   'rule', 'expired lease'));
    END IF;

    RETURN v_removed;
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

CREATE OR REPLACE FUNCTION %SCHEMA%.queue_revoke_enforcement_for_expired_actions() RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog, public'
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
    JOIN %SCHEMA%.connected_chats AS cc ON cc.is_active
    WHERE r.id = ANY(v_run_ids)
      AND NOT EXISTS (
          SELECT 1 FROM %SCHEMA%.moderation_enforcement_targets AS t
          WHERE t.run_id = r.id
      );

    RETURN v_count;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.reconcile_stuck_enforcement_targets(p_stale_after interval DEFAULT '00:15:00'::interval) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog, public'
    AS $$
DECLARE
    v_count integer;
    v_ids   bigint[];
    v_first bigint;
BEGIN
    WITH recovered AS (
        UPDATE %SCHEMA%.moderation_enforcement_targets AS t
           SET status = 'failed',
               next_retry_at = now(),
               last_error_kind = 'worker_timeout',
               last_error_detail = 'Target stayed in progress beyond the stale window and was released for retry'
         WHERE t.status = 'in_progress'
           AND t.last_attempt_at < clock_timestamp() - p_stale_after
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

CREATE OR REPLACE FUNCTION %SCHEMA%.request_user_erasure(p_user_id bigint, p_reason text, p_source text DEFAULT 'operator'::text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    v_id bigint;
BEGIN
    IF btrim(COALESCE(p_reason, '')) = '' THEN
        RAISE EXCEPTION 'An erasure request needs a reason';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM %SCHEMA%.telegram_users WHERE user_id = p_user_id) THEN
        RAISE EXCEPTION 'User % does not exist', p_user_id;
    END IF;

    IF EXISTS (SELECT 1 FROM %SCHEMA%.telegram_users
               WHERE user_id = p_user_id AND erased_at IS NOT NULL) THEN
        RAISE EXCEPTION 'User % was already erased', p_user_id;
    END IF;

    INSERT INTO %SCHEMA%.telegram_user_erasures (user_id, reason, source, status)
    VALUES (p_user_id, p_reason, p_source, 'pending')
    ON CONFLICT DO NOTHING
    RETURNING id INTO v_id;

    IF v_id IS NULL THEN
        SELECT id INTO v_id
        FROM %SCHEMA%.telegram_user_erasures
        WHERE user_id = p_user_id AND status IN ('pending', 'processing');
        RETURN v_id;
    END IF;

    INSERT INTO %SCHEMA%.audit_events (event_key, entity_type, entity_id, subject_user_id, payload)
    VALUES ('telegram.user.erasure_requested', 'telegram_user', p_user_id::text, p_user_id,
            jsonb_build_object('reason', p_reason, 'source', p_source));

    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.retention_window_days(p_target_table text) RETURNS integer
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
    SELECT COALESCE(
        (SELECT rp.retention_days
           FROM %SCHEMA%.retention_policies AS rp
          WHERE rp.target_table = p_target_table
            AND rp.is_enabled
            AND rp.retention_days IS NOT NULL),
        100000);
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.rls_auto_enable() RETURNS event_trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  cmd record;
  tbl name;
  seq record;
  fn record;
BEGIN
  FOR cmd IN
    SELECT *
    FROM pg_event_trigger_ddl_commands()
    WHERE schema_name = '%SCHEMA%'
      AND (
        (
          command_tag IN ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO')
          AND object_type IN ('table', 'partitioned table')
        )
        OR
        (
          command_tag = 'CREATE FUNCTION'
          AND object_type = 'function'
        )
      )
  LOOP
    IF cmd.object_type IN ('table', 'partitioned table') THEN
      SELECT c.relname
        INTO tbl
        FROM pg_catalog.pg_class AS c
        WHERE c.oid = cmd.objid;

      IF tbl IS NULL THEN
        RAISE EXCEPTION 'Could not resolve created public table for RLS enforcement: %',
          cmd.object_identity;
      END IF;

      EXECUTE format(
        'ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',
        cmd.schema_name,
        tbl
      );

      EXECUTE format(
        'REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM PUBLIC, anon, authenticated, service_role',
        cmd.schema_name,
        tbl
      );
      EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I.%I TO service_role',
        cmd.schema_name,
        tbl
      );

      FOR seq IN
        SELECT sn.nspname AS schema_name, s.relname AS sequence_name
        FROM pg_catalog.pg_class AS s
        JOIN pg_catalog.pg_namespace AS sn ON sn.oid = s.relnamespace
        JOIN pg_catalog.pg_depend AS d
          ON d.classid = 'pg_catalog.pg_class'::regclass
         AND d.objid = s.oid
         AND d.refclassid = 'pg_catalog.pg_class'::regclass
         AND d.refobjid = cmd.objid
         AND d.deptype IN ('a', 'i')
        WHERE s.relkind = 'S'
          AND sn.nspname = '%SCHEMA%'
      LOOP
        EXECUTE format(
          'REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM PUBLIC, anon, authenticated, service_role',
          seq.schema_name,
          seq.sequence_name
        );
        EXECUTE format(
          'GRANT USAGE, SELECT ON SEQUENCE %I.%I TO service_role',
          seq.schema_name,
          seq.sequence_name
        );
      END LOOP;

    ELSIF cmd.object_type = 'function' THEN
      SELECT n.nspname, p.proname,
             pg_get_function_identity_arguments(p.oid) AS identity_args
        INTO fn
        FROM pg_catalog.pg_proc AS p
        JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
        WHERE p.oid = cmd.objid;

      IF NOT FOUND THEN
        RAISE EXCEPTION 'Could not resolve created public function for ACL enforcement: %',
          cmd.object_identity;
      END IF;

      EXECUTE format(
        'REVOKE ALL PRIVILEGES ON FUNCTION %I.%I(%s) FROM PUBLIC, anon, authenticated, service_role',
        fn.nspname,
        fn.proname,
        fn.identity_args
      );
    END IF;
  END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.run_scheduled_job(p_job_key text) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    v_run_id      bigint;
    v_result      jsonb := '{}'::jsonb;
    v_affected    integer;
    v_status      text := 'success';
    v_error_kind  text;
    v_error_detail text;
BEGIN
    v_run_id := %SCHEMA%.scheduled_job_claim(p_job_key);

    IF v_run_id IS NULL THEN
        RETURN jsonb_build_object('job_key', p_job_key, 'skipped', true);
    END IF;

    BEGIN
        CASE p_job_key
            WHEN 'moderation.expire' THEN
                v_result := %SCHEMA%.expire_due_moderation_actions_and_queue_revokes();
                v_affected := COALESCE((v_result->>'expired_actions')::integer, 0)
                            + COALESCE((v_result->>'revoke_runs_created')::integer, 0);
            WHEN 'role.expire' THEN
                v_result := %SCHEMA%.expire_due_role_assignments_and_audit();
                v_affected := COALESCE((v_result->>'expired_role_assignments')::integer, 0);
            WHEN 'enforcement.reconcile' THEN
                v_affected := %SCHEMA%.reconcile_stuck_enforcement_targets();
                v_result := jsonb_build_object('recovered_targets', v_affected);
            WHEN 'scheduler.drift' THEN
                v_result := %SCHEMA%.audit_scheduler_drift();
                v_affected := COALESCE((v_result->>'drift_rows')::integer, 0);
            WHEN 'user.erasure' THEN
                v_affected := %SCHEMA%.sweep_pending_user_erasures();
                v_result := jsonb_build_object('erased_users', v_affected);
            WHEN 'retention.sweep' THEN
                v_result := %SCHEMA%.sweep_retention_policies();
                v_affected := COALESCE((v_result->>'removed_total')::integer, 0);
            ELSE
                RAISE EXCEPTION 'No dispatcher is registered for scheduled job %', p_job_key;
        END CASE;
    EXCEPTION WHEN OTHERS THEN
        v_status := 'failed';
        v_error_kind := 'job_error';
        v_error_detail := SQLERRM;
    END;

    PERFORM %SCHEMA%.scheduled_job_finish(
        v_run_id, v_status, v_affected, v_error_kind, v_error_detail, v_result);

    IF v_status = 'failed' THEN
        RAISE EXCEPTION 'Scheduled job % failed: %', p_job_key, v_error_detail;
    END IF;

    RETURN jsonb_build_object('job_key', p_job_key,
                              'run_id', v_run_id,
                              'affected', v_affected,
                              'result', v_result);
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.safe_duration_ms(p_interval interval) RETURNS integer
    LANGUAGE sql IMMUTABLE
    SET search_path TO 'pg_catalog'
    AS $$
    SELECT LEAST(
        2147483647::bigint,
        GREATEST(0::bigint, (extract(epoch FROM p_interval) * 1000)::bigint)
    )::integer;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.scheduled_job_claim(p_job_key text, p_run_key text DEFAULT NULL::text, p_triggered_by text DEFAULT 'cron'::text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog, public'
    AS $$
DECLARE
    v_job        %SCHEMA%.scheduled_jobs%ROWTYPE;
    v_run_id     bigint;
    v_run_key    text;
    v_stuck_id   bigint;
    v_stuck_at   timestamptz;
BEGIN
    SELECT * INTO v_job
    FROM %SCHEMA%.scheduled_jobs
    WHERE job_key = p_job_key
    FOR UPDATE SKIP LOCKED;

    IF NOT FOUND THEN
        IF EXISTS (SELECT 1 FROM %SCHEMA%.scheduled_jobs WHERE job_key = p_job_key) THEN
            RETURN NULL;
        END IF;
        RAISE EXCEPTION 'Scheduled job % is not registered', p_job_key;
    END IF;

    IF NOT v_job.is_enabled THEN
        RETURN NULL;
    END IF;

    SELECT id, started_at INTO v_stuck_id, v_stuck_at
    FROM %SCHEMA%.scheduled_job_runs
    WHERE job_key = p_job_key AND status = 'running'
    ORDER BY started_at DESC
    LIMIT 1;

    IF v_stuck_id IS NOT NULL THEN
        IF v_stuck_at > clock_timestamp() - make_interval(secs => v_job.timeout_seconds) THEN
            RETURN NULL;
        END IF;

        UPDATE %SCHEMA%.scheduled_job_runs
           SET status = 'failed',
               finished_at = clock_timestamp(),
               error_kind = 'job_timeout',
               error_detail = 'Execution exceeded the registered timeout window and was reclaimed'
         WHERE id = v_stuck_id;

        INSERT INTO %SCHEMA%.audit_events (event_key, entity_type, entity_id, payload)
        VALUES ('scheduler.job.timeout',
                'scheduled_job',
                p_job_key,
                jsonb_build_object('run_id', v_stuck_id,
                                   'timeout_seconds', v_job.timeout_seconds));
    END IF;

    v_run_key := COALESCE(
        p_run_key,
        format('%s:%s', p_job_key, to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYYMMDDHH24MI'))
    );

    IF EXISTS (SELECT 1 FROM %SCHEMA%.scheduled_job_runs WHERE run_key = v_run_key) THEN
        RETURN NULL;
    END IF;

    INSERT INTO %SCHEMA%.scheduled_job_runs (job_key, run_key, triggered_by, status)
    VALUES (p_job_key, v_run_key, p_triggered_by, 'running')
    RETURNING id INTO v_run_id;

    UPDATE %SCHEMA%.scheduled_jobs
       SET last_started_at = clock_timestamp(),
           last_status = 'running',
           updated_at = clock_timestamp()
     WHERE job_key = p_job_key;

    RETURN v_run_id;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.scheduled_job_finish(p_run_id bigint, p_status text, p_affected integer DEFAULT NULL::integer, p_error_kind text DEFAULT NULL::text, p_error_detail text DEFAULT NULL::text, p_payload jsonb DEFAULT '{}'::jsonb) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    v_run    %SCHEMA%.scheduled_job_runs%ROWTYPE;
    v_status text;
BEGIN
    IF p_status NOT IN ('success', 'failed', 'skipped') THEN
        RAISE EXCEPTION 'A scheduled job run must finish as success, failed, or skipped';
    END IF;

    SELECT * INTO v_run
    FROM %SCHEMA%.scheduled_job_runs
    WHERE id = p_run_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Scheduled job run % does not exist', p_run_id;
    END IF;

    v_status := p_status;

    UPDATE %SCHEMA%.scheduled_job_runs
       SET status = v_status,
           finished_at = now(),
           affected_count = p_affected,
           error_kind = p_error_kind,
           error_detail = p_error_detail,
           payload = COALESCE(p_payload, '{}'::jsonb)
     WHERE id = p_run_id;

    UPDATE %SCHEMA%.scheduled_jobs
       SET last_status = v_status,
           last_success_at = CASE WHEN v_status = 'success' THEN now() ELSE last_success_at END,
           consecutive_failures = CASE WHEN v_status = 'success' THEN 0 ELSE consecutive_failures + 1 END,
           last_error = CASE WHEN v_status = 'success' THEN NULL ELSE COALESCE(p_error_detail, p_error_kind) END,
           last_duration_ms = %SCHEMA%.safe_duration_ms(now() - v_run.started_at),
           updated_at = now()
     WHERE job_key = v_run.job_key;

    INSERT INTO %SCHEMA%.audit_events (event_key, entity_type, entity_id, payload)
    VALUES ('scheduler.job.completed',
            'scheduled_job',
            v_run.job_key,
            jsonb_build_object('run_id', p_run_id,
                               'status', v_status,
                               'affected_count', p_affected,
                               'error_kind', p_error_kind));
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.scheduler_drift_report() RETURNS TABLE(job_key text, in_registry boolean, registered_in_cron boolean, cron_active boolean, cron_schedule text, cron_command text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog, public, cron'
    AS $$
BEGIN
    RETURN QUERY
    SELECT * FROM (
        SELECT j.job_key AS job_key,
               true AS in_registry,
               (c.jobid IS NOT NULL) AS registered_in_cron,
               COALESCE(c.active, false) AS cron_active,
               c.schedule AS cron_schedule,
               c.command AS cron_command
        FROM %SCHEMA%.scheduled_jobs AS j
        LEFT JOIN cron.job AS c ON c.jobname = j.job_key
        UNION ALL
        SELECT c.jobname AS job_key,
               false AS in_registry,
               true AS registered_in_cron,
               COALESCE(c.active, false) AS cron_active,
               c.schedule AS cron_schedule,
               c.command AS cron_command
        FROM cron.job AS c
        WHERE c.jobname NOT IN (SELECT sj.job_key FROM %SCHEMA%.scheduled_jobs AS sj)
    ) AS drift
    ORDER BY drift.job_key;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.sweep_pending_user_erasures(p_limit integer DEFAULT 50) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    v_req %SCHEMA%.telegram_user_erasures%ROWTYPE;
    v_done integer := 0;
BEGIN
    FOR v_req IN
        SELECT * FROM %SCHEMA%.telegram_user_erasures
        WHERE status = 'pending'
        ORDER BY requested_at
        LIMIT GREATEST(p_limit, 0)
    LOOP
        BEGIN
            PERFORM %SCHEMA%.process_user_erasure(v_req.id);
            v_done := v_done + 1;
        EXCEPTION WHEN OTHERS THEN
            UPDATE %SCHEMA%.telegram_user_erasures
               SET status = 'retained',
                   processed_at = now(),
                   notes = 'Erasure could not be completed: ' || SQLERRM
             WHERE id = v_req.id;
        END;
    END LOOP;

    RETURN v_done;
END;
$$;

CREATE OR REPLACE FUNCTION %SCHEMA%.sweep_retention_policies() RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    r        record;
    v_total  integer := 0;
    v_count  integer;
    v_detail jsonb := '{}'::jsonb;
BEGIN
    FOR r IN
        SELECT target_table FROM %SCHEMA%.retention_policies
        WHERE is_enabled AND retention_days IS NOT NULL
        ORDER BY target_table
    LOOP
        v_count := %SCHEMA%.apply_retention_policy(r.target_table);
        IF v_count > 0 THEN
            v_detail := jsonb_set(v_detail, ARRAY[r.target_table], to_jsonb(v_count), true);
        END IF;
        v_total := v_total + v_count;
    END LOOP;

    v_count := %SCHEMA%.prune_expired_mtproto_state();
    IF v_count > 0 THEN
        v_detail := jsonb_set(v_detail, ARRAY['mtproto_state'], to_jsonb(v_count), true);
        v_total := v_total + v_count;
    END IF;

    RETURN jsonb_build_object('removed_total', v_total, 'by_table', v_detail);
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

CREATE OR REPLACE FUNCTION %SCHEMA%.validate_connected_chat_chat_type() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE v_chat_type text;
BEGIN
  SELECT chat_type INTO v_chat_type
  FROM %SCHEMA%.telegram_chats WHERE chat_id = NEW.chat_id;
  IF NOT FOUND OR v_chat_type NOT IN ('group', 'supergroup') THEN
    RAISE EXCEPTION 'Managed community chats must be Telegram groups or supergroups';
  END IF;
  RETURN NEW;
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
