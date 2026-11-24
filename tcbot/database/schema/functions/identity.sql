-- The database functions that own the state transitions.
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
    SET search_path TO 'pg_catalog', '%SCHEMA%'
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

    -- * The new chat inherits the connection state of the group it
    -- * replaces: a group the operator disconnected stays disconnected.
    -- * A row that already exists for the new chat keeps its own state,
    -- * because that row records a decision the operator took about that
    -- * chat, and a repoint must not undo it.
    INSERT INTO %SCHEMA%.connected_chats (
        chat_id, added_by_user_id, added_at, is_active
    )
    SELECT p_new_chat_id, g.added_by_user_id, g.added_at,
           COALESCE(v_was_active, false)
      FROM %SCHEMA%.connected_chats AS g
     WHERE g.chat_id = p_old_chat_id
    ON CONFLICT (chat_id) DO UPDATE
        SET added_by_user_id = COALESCE(
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

CREATE OR REPLACE FUNCTION %SCHEMA%.guard_erased_user_identity() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
  -- * Erasure keeps the identity row for history but clears its profile.
  -- * Ordinary updates harvest that profile from every later Telegram
  -- * update, so without this guard an erased account is repopulated and
  -- * cannot be erased again. Clearing fields is always allowed, which
  -- * lets the erasure sweep itself run and be repeated.
  IF TG_OP = 'UPDATE' AND OLD.erased_at IS NOT NULL THEN
    IF (NEW.username IS NOT NULL AND btrim(NEW.username) <> '')
       OR (NEW.first_name IS NOT NULL AND btrim(NEW.first_name) <> '')
       OR (NEW.last_name IS NOT NULL AND btrim(NEW.last_name) <> '')
       OR (NEW.language_code IS NOT NULL AND btrim(NEW.language_code) <> '')
       OR NEW.is_premium THEN
      RAISE EXCEPTION USING
        ERRCODE = '23514',
        CONSTRAINT = 'ck_telegram_users_erased_identity',
        MESSAGE = 'An erased user identity cannot be repopulated';
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

CREATE OR REPLACE FUNCTION %SCHEMA%.prevent_historical_record_delete() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
    BEGIN
      RAISE EXCEPTION 'Historical record in % is append-only; use its lifecycle state instead of deleting it', TG_TABLE_NAME;
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
