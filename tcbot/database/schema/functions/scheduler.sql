-- The database functions that own the state transitions.
CREATE OR REPLACE FUNCTION %SCHEMA%.audit_scheduler_drift() RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO pg_catalog, '%SCHEMA%', cron
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

CREATE OR REPLACE FUNCTION %SCHEMA%.run_scheduled_job(p_job_key text, p_run_key text DEFAULT NULL) RETURNS jsonb
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
    v_run_id := %SCHEMA%.scheduled_job_claim(p_job_key, p_run_key);

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

    -- * The failure must commit its run row before the caller raises. A
    -- * RAISE here would roll the whole transaction back, including the
    -- * claim and the finish record, and the registry would keep reporting
    -- * the previous successful run.
    RETURN jsonb_build_object('job_key', p_job_key,
                              'run_id', v_run_id,
                              'affected', v_affected,
                              'status', v_status,
                              'error', v_error_detail,
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
    SET search_path TO 'pg_catalog', '%SCHEMA%'
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
    SET search_path TO pg_catalog, '%SCHEMA%', cron
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
        WHERE j.job_owner = 'pg_cron'
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
