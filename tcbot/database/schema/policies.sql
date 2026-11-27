-- The access policies of the schema.
--
-- Every base table carries row level security, and the exposed API roles
-- are denied explicitly. The denial is a policy rather than the absence
-- of a policy, so a later permissive policy cannot open a table by
-- accident.
--
-- The statements are idempotent: the policy is dropped and recreated,
-- and the row level security is enabled again. The roles are checked
-- first, because a plain PostgreSQL server does not carry them.
--
-- The schema placeholder is the same one every other schema file uses.
-- The loader substitutes the quoted identifier, so the quote marks are
-- trimmed before the name reaches format('%I', ...).

DO $do$
DECLARE
    v_schema text := btrim('%SCHEMA%', '"');
    table_name text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        RETURN;
    END IF;

    FOREACH table_name IN ARRAY ARRAY[
        'community_settings',
        'telegram_users',
        'telegram_chats',
        'connected_chats',
        'join_requests',
        'role_definitions',
        'permission_definitions',
        'role_permissions',
        'role_assignments',
        'promotion_requests',
        'user_settings',
        'chat_settings',
        'chat_members',
        'moderation_cases',
        'moderation_evidence_uploads',
        'moderation_evidence_items',
        'moderation_actions',
        'moderation_appeals',
        'moderation_messages',
        'moderation_notification_tasks',
        'audit_events',
        'moderation_enforcement_runs',
        'moderation_enforcement_targets',
        'moderation_enforcement_attempts',
        'automation_policies',
        'automation_policy_versions',
        'automation_events',
        'automation_runs',
        'automation_run_steps',
        'automation_run_step_attempts',
        'broadcast_campaigns',
        'broadcast_targets',
        'broadcast_attempts',
        'scheduled_jobs',
        'scheduled_job_runs',
        'telegram_user_erasures',
        'retention_policies',
        'mtproto_state',
        'apscheduler_jobs'
    ] LOOP
        -- * An early schema reapply runs these current files against an older
        -- * table set. Skip tables introduced by a later revision instead of
        -- * aborting the whole script on a missing relation.
        CONTINUE WHEN to_regclass(format('%I.%I', v_schema, table_name)) IS NULL;
        EXECUTE format(
            'ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',
            v_schema, table_name
        );
        EXECUTE format(
            'DROP POLICY IF EXISTS deny_exposed_api_roles ON %I.%I',
            v_schema, table_name
        );
        EXECUTE format(
            'CREATE POLICY deny_exposed_api_roles ON %I.%I TO authenticated, anon USING (false) WITH CHECK (false)',
            v_schema, table_name
        );
    END LOOP;
END;
$do$;

-- The views read the tables with the rights of the caller, so the
-- exposed API roles do not get a grant on them either.
DO $do$
DECLARE
    v_schema text := btrim('%SCHEMA%', '"');
    view_name text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        RETURN;
    END IF;

    FOREACH view_name IN ARRAY ARRAY[
        'active_bans',
        'active_mutes',
        'community_member_stats',
        'community_members',
        'effective_chat_settings',
        'moderation_timeline',
        'role_permission_matrix',
        'warn_counts'
    ] LOOP
        -- * A view introduced by a later revision is not there to revoke.
        CONTINUE WHEN to_regclass(format('%I.%I', v_schema, view_name)) IS NULL;
        EXECUTE format(
            'REVOKE ALL ON %I.%I FROM anon, authenticated',
            v_schema, view_name
        );
    END LOOP;
END;
$do$;
