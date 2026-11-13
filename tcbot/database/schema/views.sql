-- The read-only views of the community.
CREATE OR REPLACE VIEW %SCHEMA%.active_bans WITH (security_invoker='true') AS
 SELECT id AS ban_action_id,
    external_ref AS ban_id,
    scope_type,
    chat_id,
    origin_chat_id,
    target_user_id AS banned_user_id,
    actor_user_id AS admin_user_id,
    reason,
    created_at AS "timestamp",
    expires_at AS until_date,
    duration_seconds,
    metadata
   FROM %SCHEMA%.moderation_actions
  WHERE ((action_type = 'ban'::text) AND (status = 'active'::text) AND ((expires_at IS NULL) OR (expires_at > now())));

CREATE OR REPLACE VIEW %SCHEMA%.active_mutes WITH (security_invoker='true') AS
 SELECT id AS mute_id,
    scope_type,
    chat_id,
    origin_chat_id,
    target_user_id AS user_id,
    actor_user_id AS admin_id,
    reason,
    created_at AS "timestamp",
    expires_at AS until_date,
    duration_seconds,
    metadata
   FROM %SCHEMA%.moderation_actions
  WHERE ((action_type = 'mute'::text) AND (status = 'active'::text) AND ((expires_at IS NULL) OR (expires_at > now())));

CREATE OR REPLACE VIEW %SCHEMA%.community_member_stats WITH (security_invoker='true') AS
 SELECT ( SELECT count(DISTINCT cm.user_id) AS count
           FROM (%SCHEMA%.chat_members cm
             JOIN %SCHEMA%.connected_chats cc ON (((cc.chat_id = cm.chat_id) AND cc.is_active)))
          WHERE (cm.status = ANY (ARRAY['creator'::text, 'administrator'::text, 'member'::text, 'restricted'::text]))) AS unique_members,
    ( SELECT count(*) AS count
           FROM (%SCHEMA%.chat_members cm
             JOIN %SCHEMA%.connected_chats cc ON (((cc.chat_id = cm.chat_id) AND cc.is_active)))
          WHERE (cm.status = ANY (ARRAY['creator'::text, 'administrator'::text, 'member'::text, 'restricted'::text]))) AS active_memberships,
    ( SELECT count(*) AS count
           FROM %SCHEMA%.connected_chats cc
          WHERE cc.is_active) AS active_connected_chats;

CREATE OR REPLACE VIEW %SCHEMA%.community_members WITH (security_invoker='true') AS
 SELECT tu.user_id,
    tu.username,
    tu.first_name,
    tu.last_name,
    tu.language_code,
    tu.is_bot,
    tu.is_premium,
    min(cm.joined_at) AS first_joined_at,
    max(cm.last_seen_at) AS last_seen_at,
    (count(DISTINCT cm.chat_id))::integer AS connected_group_count,
    bool_or((cm.status = ANY (ARRAY['creator'::text, 'administrator'::text]))) AS has_telegram_admin_membership
   FROM ((%SCHEMA%.telegram_users tu
     JOIN %SCHEMA%.chat_members cm ON ((cm.user_id = tu.user_id)))
     JOIN %SCHEMA%.connected_chats cc ON (((cc.chat_id = cm.chat_id) AND cc.is_active)))
  WHERE (cm.status = ANY (ARRAY['creator'::text, 'administrator'::text, 'member'::text, 'restricted'::text]))
  GROUP BY tu.user_id, tu.username, tu.first_name, tu.last_name, tu.language_code, tu.is_bot, tu.is_premium;

CREATE OR REPLACE VIEW %SCHEMA%.effective_chat_settings WITH (security_invoker='true') AS
 SELECT cc.chat_id,
    tc.title AS chat_title,
    cc.is_active,
    COALESCE(cs.locale, global_settings.default_locale) AS locale,
    COALESCE(cs.timezone, global_settings.timezone) AS timezone,
    (COALESCE(global_settings.settings, '{}'::jsonb) || COALESCE(cs.settings, '{}'::jsonb)) AS settings
   FROM (((%SCHEMA%.connected_chats cc
     JOIN %SCHEMA%.telegram_chats tc ON ((tc.chat_id = cc.chat_id)))
     CROSS JOIN %SCHEMA%.community_settings global_settings)
     LEFT JOIN %SCHEMA%.chat_settings cs ON ((cs.chat_id = cc.chat_id)))
  WHERE cc.is_active;

CREATE OR REPLACE VIEW %SCHEMA%.moderation_timeline WITH (security_invoker='true') AS
 SELECT a.target_user_id AS subject_user_id,
    a.case_id,
    a.id AS action_id,
    'action'::text AS kind,
    (a.id)::text AS ref_id,
    a.actor_user_id,
    a.created_at AS occurred_at,
    a.status,
    (a.action_type || ' action'::text) AS summary,
    jsonb_build_object('action_type', a.action_type, 'scope_type', a.scope_type, 'chat_id', a.chat_id, 'origin_chat_id', a.origin_chat_id, 'reason', a.reason, 'action_origin', a.action_origin, 'expires_at', a.expires_at, 'external_ref', a.external_ref) AS metadata
   FROM %SCHEMA%.moderation_actions a
UNION ALL
 SELECT a.target_user_id AS subject_user_id,
    a.case_id,
    ap.action_id,
    'appeal'::text AS kind,
    (ap.id)::text AS ref_id,
    ap.reviewed_by_user_id AS actor_user_id,
    ap.submitted_at AS occurred_at,
    ap.status,
    ('appeal '::text || ap.status) AS summary,
    jsonb_build_object('appeal_text', ap.appeal_text, 'decision_note', ap.decision_note, 'resolved_at', ap.resolved_at) AS metadata
   FROM (%SCHEMA%.moderation_appeals ap
     JOIN %SCHEMA%.moderation_actions a ON ((a.id = ap.action_id)))
UNION ALL
 SELECT c.subject_user_id,
    eu.case_id,
    NULL::bigint AS action_id,
    'evidence'::text AS kind,
    (eu.id)::text AS ref_id,
    eu.uploaded_by_user_id AS actor_user_id,
    eu.created_at AS occurred_at,
    eu.status,
    ('evidence upload '::text || eu.status) AS summary,
    jsonb_build_object('destination_chat_id', eu.destination_chat_id, 'expected_item_count', eu.expected_item_count, 'is_required', eu.is_required, 'failure_code', eu.failure_code) AS metadata
   FROM (%SCHEMA%.moderation_evidence_uploads eu
     JOIN %SCHEMA%.moderation_cases c ON ((c.id = eu.case_id)))
UNION ALL
 SELECT c.subject_user_id,
    eu.case_id,
    NULL::bigint AS action_id,
    'evidence_item'::text AS kind,
    (ei.id)::text AS ref_id,
    NULL::bigint AS actor_user_id,
    ei.created_at AS occurred_at,
    NULL::text AS status,
    ('archived '::text || ei.media_type) AS summary,
    jsonb_build_object('upload_id', ei.upload_id, 'media_type', ei.media_type, 'item_order', ei.item_order, 'media_group_id', ei.media_group_id, 'archive_message_id', ei.archive_message_id, 'sha256_hex', ei.sha256_hex) AS metadata
   FROM ((%SCHEMA%.moderation_evidence_items ei
     JOIN %SCHEMA%.moderation_evidence_uploads eu ON ((eu.id = ei.upload_id)))
     JOIN %SCHEMA%.moderation_cases c ON ((c.id = eu.case_id)))
UNION ALL
 SELECT a.target_user_id AS subject_user_id,
    a.case_id,
    r.action_id,
    'enforcement_run'::text AS kind,
    (r.id)::text AS ref_id,
    r.requested_by_user_id AS actor_user_id,
    r.created_at AS occurred_at,
    r.status,
    (r.operation || ' enforcement run'::text) AS summary,
    jsonb_build_object('operation', r.operation, 'target_count', r.target_count, 'succeeded_count', r.succeeded_count, 'failed_count', r.failed_count, 'skipped_count', r.skipped_count, 'scheduled_job_run_id', r.scheduled_job_run_id) AS metadata
   FROM (%SCHEMA%.moderation_enforcement_runs r
     JOIN %SCHEMA%.moderation_actions a ON ((a.id = r.action_id)))
UNION ALL
 SELECT a.target_user_id AS subject_user_id,
    a.case_id,
    r.action_id,
    'enforcement_target'::text AS kind,
    (t.id)::text AS ref_id,
    NULL::bigint AS actor_user_id,
    t.created_at AS occurred_at,
    t.status,
    ('enforcement target '::text || t.status) AS summary,
    jsonb_build_object('run_id', t.run_id, 'chat_id', t.chat_id, 'attempt_count', t.attempt_count, 'next_retry_at', t.next_retry_at, 'last_error_kind', t.last_error_kind, 'last_error_code', t.last_error_code) AS metadata
   FROM ((%SCHEMA%.moderation_enforcement_targets t
     JOIN %SCHEMA%.moderation_enforcement_runs r ON ((r.id = t.run_id)))
     JOIN %SCHEMA%.moderation_actions a ON ((a.id = r.action_id)))
UNION ALL
 SELECT a.target_user_id AS subject_user_id,
    a.case_id,
    r.action_id,
    'enforcement_attempt'::text AS kind,
    (att.id)::text AS ref_id,
    NULL::bigint AS actor_user_id,
    att.attempted_at AS occurred_at,
    att.outcome AS status,
    ((('attempt '::text || (att.attempt_number)::text) || ' '::text) || att.outcome) AS summary,
    jsonb_build_object('target_id', att.target_id, 'attempt_number', att.attempt_number, 'error_kind', att.error_kind, 'error_code', att.error_code) AS metadata
   FROM (((%SCHEMA%.moderation_enforcement_attempts att
     JOIN %SCHEMA%.moderation_enforcement_targets t ON ((t.id = att.target_id)))
     JOIN %SCHEMA%.moderation_enforcement_runs r ON ((r.id = t.run_id)))
     JOIN %SCHEMA%.moderation_actions a ON ((a.id = r.action_id)))
UNION ALL
 SELECT ae.subject_user_id,
    ae.case_id,
    ae.action_id,
    'audit'::text AS kind,
    (ae.id)::text AS ref_id,
    ae.actor_user_id,
    ae.occurred_at,
    NULL::text AS status,
    ae.event_key AS summary,
    jsonb_build_object('entity_type', ae.entity_type, 'entity_id', ae.entity_id, 'correlation_id', ae.correlation_id, 'operation_id', ae.operation_id, 'payload', ae.payload) AS metadata
   FROM %SCHEMA%.audit_events ae;

CREATE OR REPLACE VIEW %SCHEMA%.role_permission_matrix WITH (security_invoker='true') AS
 SELECT rd.role_key,
    rd.display_name,
    rd.description,
    rd.priority,
    rd.is_system,
    (count(rp.permission_key))::integer AS permission_count,
    COALESCE(array_agg(rp.permission_key ORDER BY rp.permission_key) FILTER (WHERE (rp.permission_key IS NOT NULL)), '{}'::text[]) AS permissions,
    COALESCE(( SELECT array_agg(pd.permission_key ORDER BY pd.permission_key) AS array_agg
           FROM %SCHEMA%.permission_definitions pd
          WHERE ((pd.permission_key IN ( SELECT role_permissions.permission_key
                   FROM %SCHEMA%.role_permissions
                  WHERE (role_permissions.role_key = 'owner'::text))) AND (NOT (EXISTS ( SELECT 1
                   FROM %SCHEMA%.role_permissions rp2
                  WHERE ((rp2.role_key = rd.role_key) AND (rp2.permission_key = pd.permission_key))))))), '{}'::text[]) AS missing_from_owner
   FROM (%SCHEMA%.role_definitions rd
     LEFT JOIN %SCHEMA%.role_permissions rp ON ((rp.role_key = rd.role_key)))
  GROUP BY rd.role_key, rd.display_name, rd.description, rd.priority, rd.is_system;

CREATE OR REPLACE VIEW %SCHEMA%.warn_counts WITH (security_invoker='true') AS
 SELECT chat_id,
    target_user_id AS user_id,
    (count(*))::integer AS count,
    max(created_at) AS updated_at
   FROM %SCHEMA%.moderation_actions
  WHERE ((action_type = 'warn'::text) AND (status = 'completed'::text) AND ((expires_at IS NULL) OR (expires_at > now())))
  GROUP BY chat_id, target_user_id;
