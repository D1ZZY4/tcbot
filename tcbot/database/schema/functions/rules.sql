-- Rule sets, versions, items, and publication guards.

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

CREATE OR REPLACE FUNCTION %SCHEMA%.validate_rule_publication_scope() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
  v_rule_set_id bigint;
  v_locale text;
BEGIN
  SELECT rsv.rule_set_id, rsv.locale
    INTO v_rule_set_id, v_locale
    FROM %SCHEMA%.rule_set_versions AS rsv
   WHERE rsv.id = NEW.rule_set_version_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Publication version does not exist';
  END IF;
  IF NEW.rule_set_id IS DISTINCT FROM v_rule_set_id
     OR NEW.locale IS DISTINCT FROM v_locale THEN
    RAISE EXCEPTION 'Publication set and locale must match its version';
  END IF;
  RETURN NEW;
END;
$$;
