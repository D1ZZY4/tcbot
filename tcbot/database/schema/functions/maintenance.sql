-- The database functions that own the state transitions.
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

CREATE OR REPLACE FUNCTION %SCHEMA%.process_user_erasure(p_erasure_id bigint) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', '%SCHEMA%'
    AS $$
DECLARE
    v_req          %SCHEMA%.telegram_user_erasures%ROWTYPE;
    v_affected     jsonb := '{}'::jsonb;
    v_count        integer;
    v_action_count integer := 0;
    v_action_id    bigint;
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

    -- * Erasing the current owner would revoke the only Owner row, and a
    -- * restart could recreate that role for the erased account. The
    -- * operator must transfer ownership first; the sweep records the
    -- * refused request as retained.
    IF EXISTS (
        SELECT 1
          FROM %SCHEMA%.role_assignments AS ra
         WHERE ra.user_id = v_req.user_id
           AND ra.role_key = 'owner'
           AND ra.status = 'active'
           AND (ra.expires_at IS NULL OR ra.expires_at > now())
    ) THEN
        RAISE EXCEPTION 'The current federation owner cannot be erased';
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

    -- * A revoked ban must not leave a pending appeal and a live review
    -- * card behind: the card would only be able to reject a decision that
    -- * no longer exists.
    UPDATE %SCHEMA%.moderation_appeals AS ap
       SET status = 'withdrawn',
           resolved_at = now(),
           decision_note = 'Account erased'
      WHERE ap.status = 'pending'
        AND ap.action_id IN (
            SELECT a.id
              FROM %SCHEMA%.moderation_actions AS a
             WHERE a.target_user_id = v_req.user_id
               AND a.status = 'active'
        );
    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_affected := jsonb_set(v_affected, '{appeals_withdrawn}', to_jsonb(v_count), true);

    FOR v_action_id IN
        UPDATE %SCHEMA%.moderation_actions
           SET status = 'revoked',
               revoked_at = now(),
               metadata = metadata - 'review_message_id' - 'review_timestamp'
         WHERE target_user_id = v_req.user_id
           AND status = 'active'
        RETURNING id
    LOOP
        v_action_count := v_action_count + 1;
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

    v_affected := jsonb_set(
        v_affected,
        '{moderation_actions_revoked}',
        to_jsonb(v_action_count),
        true
    );

    -- * A request filed before the erasure could otherwise be approved
    -- * later and grant a role to an account that no longer exists.
    UPDATE %SCHEMA%.promotion_requests
       SET status = 'cancelled',
           resolved_at = now(),
           decision_note = 'Target account erased'
     WHERE target_user_id = v_req.user_id
       AND status = 'pending';
    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_affected := jsonb_set(v_affected, '{promotion_requests_cancelled}', to_jsonb(v_count), true);

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
        -- * The id tie-break matches the caller's pre-read, so the ids it
        -- * invalidates in the cache are exactly the rows this batch
        -- * erased even when several requests share a timestamp.
        ORDER BY requested_at, id
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
