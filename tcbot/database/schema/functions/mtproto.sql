-- MTProto session state: leased access and lookup helpers.

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
