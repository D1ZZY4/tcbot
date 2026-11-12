INSERT INTO public.role_definitions
    (role_key, display_name, description, priority, is_system)
VALUES
    ('developer', 'Developer',
     'Compatibility tier for the existing TCBot Developer role. Sits above Moderator and below Administrator.',
     60, false)
ON CONFLICT (role_key) DO NOTHING;

INSERT INTO public.permission_definitions
    (permission_key, description, resource)
VALUES
    ('moderation.ban', 'Create or update a federation-wide ban.', 'moderation'),
    ('moderation.unban', 'Deactivate a federation-wide ban and reconcile Telegram restrictions.', 'moderation'),
    ('moderation.sync', 'Run bounded enforcement reconciliation across connected groups.', 'moderation'),
    ('moderation.kick', 'Kick a user from a connected group.', 'moderation'),
    ('moderation.mute', 'Apply a federation-wide mute.', 'moderation'),
    ('moderation.unmute', 'Remove a federation-wide mute.', 'moderation'),
    ('moderation.warn', 'Issue a warning in a connected group.', 'moderation'),
    ('moderation.unwarn', 'Remove a warning.', 'moderation'),
    ('moderation.reset_warnings', 'Reset warning history or counters.', 'moderation'),
    ('moderation.review_appeals', 'Approve or reject moderation appeals.', 'moderation'),
    ('roles.promote', 'Assign a lower-ranked federation staff role.', 'roles'),
    ('roles.demote', 'Revoke a lower-ranked federation staff role.', 'roles'),
    ('roles.view_promotion_requests', 'List pending promotion requests.', 'roles'),
    ('roles.review_promotion_requests', 'Approve or reject promotion requests.', 'roles'),
    ('roles.transfer_ownership', 'Transfer federation ownership.', 'roles'),
    ('federation.broadcast', 'Broadcast a message to connected federation groups.', 'federation'),
    ('federation.cleanup', 'Remove groups the bot can no longer access.', 'federation'),
    ('federation.remove_group', 'Force-remove a group from the federation.', 'federation'),
    ('federation.leave_all', 'Leave all managed federation groups.', 'federation'),
    ('federation.speedtest', 'Run a host network speed test.', 'federation')
ON CONFLICT (permission_key) DO UPDATE
SET description = EXCLUDED.description,
    resource = EXCLUDED.resource;

INSERT INTO public.role_permissions (role_key, permission_key)
VALUES
    ('owner', 'moderation.ban'),
    ('owner', 'moderation.unban'),
    ('owner', 'moderation.sync'),
    ('owner', 'moderation.kick'),
    ('owner', 'moderation.mute'),
    ('owner', 'moderation.unmute'),
    ('owner', 'moderation.warn'),
    ('owner', 'moderation.unwarn'),
    ('owner', 'moderation.reset_warnings'),
    ('owner', 'moderation.review_appeals'),
    ('owner', 'roles.promote'),
    ('owner', 'roles.demote'),
    ('owner', 'roles.view_promotion_requests'),
    ('owner', 'roles.review_promotion_requests'),
    ('owner', 'roles.transfer_ownership'),
    ('owner', 'federation.broadcast'),
    ('owner', 'federation.cleanup'),
    ('owner', 'federation.remove_group'),
    ('owner', 'federation.leave_all'),
    ('owner', 'federation.speedtest'),

    ('admin', 'moderation.ban'),
    ('admin', 'moderation.unban'),
    ('admin', 'moderation.sync'),
    ('admin', 'moderation.kick'),
    ('admin', 'moderation.mute'),
    ('admin', 'moderation.unmute'),
    ('admin', 'moderation.warn'),
    ('admin', 'moderation.unwarn'),
    ('admin', 'moderation.reset_warnings'),
    ('admin', 'moderation.review_appeals'),
    ('admin', 'roles.promote'),
    ('admin', 'roles.demote'),
    ('admin', 'roles.view_promotion_requests'),
    ('admin', 'federation.broadcast'),
    ('admin', 'federation.cleanup'),
    ('admin', 'federation.remove_group'),

    ('developer', 'moderation.ban'),
    ('developer', 'moderation.unban'),
    ('developer', 'moderation.sync'),
    ('developer', 'moderation.kick'),
    ('developer', 'moderation.mute'),
    ('developer', 'moderation.unmute'),
    ('developer', 'moderation.warn'),
    ('developer', 'moderation.unwarn'),
    ('developer', 'moderation.reset_warnings'),

    ('moderator', 'moderation.kick'),
    ('moderator', 'moderation.mute'),
    ('moderator', 'moderation.unmute'),
    ('moderator', 'moderation.warn'),
    ('moderator', 'moderation.unwarn'),
    ('moderator', 'moderation.reset_warnings')
ON CONFLICT (role_key, permission_key) DO NOTHING;
