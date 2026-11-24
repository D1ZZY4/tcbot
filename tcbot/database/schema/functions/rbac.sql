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
    SET search_path TO 'pg_catalog', '%SCHEMA%'
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
  IF NEW.status NOT IN ('pending','approved','rejected','cancelled','expired') THEN
    RAISE EXCEPTION 'Invalid promotion request transition: % -> %', OLD.status, NEW.status;
  END IF;
  IF NEW.status = 'pending' THEN
    IF NEW.resolved_by_user_id IS NOT NULL OR NEW.resolved_at IS NOT NULL THEN
      RAISE EXCEPTION 'Pending promotion requests cannot have resolution metadata';
    END IF;
  ELSIF NEW.status = 'expired' THEN
    IF NEW.expires_at IS NULL OR NEW.expires_at > now() THEN
      RAISE EXCEPTION 'Only promotion requests whose expiry time has passed can become expired';
    END IF;
    NEW.resolved_at := COALESCE(NEW.resolved_at, now());
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

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
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

    IF v_request.expires_at IS NOT NULL AND v_request.expires_at <= now() THEN
        RAISE EXCEPTION 'Promotion request % has expired', p_request_id;
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

    IF v_request.expires_at IS NOT NULL AND v_request.expires_at <= now() THEN
        RAISE EXCEPTION 'Promotion request % has expired', p_request_id;
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

    -- * The audit entity_id must be the numeric primary key: the audit guard
    -- * validates promotion_request ids against promotion_requests.id. Passing
    -- * the public short text id aborted the whole rejection.
    INSERT INTO %SCHEMA%.audit_events (event_key, entity_type, entity_id, subject_user_id, actor_user_id, payload)
    VALUES ('role.promotion.rejected', 'promotion_request', v_request.id::text, v_request.target_user_id, p_actor_user_id,
            jsonb_build_object('request_id', p_request_id,
                               'role_key', v_request.requested_role_key,
                               'decision_note', p_decision_note));
END;
$$;
