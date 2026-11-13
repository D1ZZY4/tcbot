-- The triggers that protect the invariants the schema cannot express.
CREATE TRIGGER assign_moderation_action_external_ref BEFORE INSERT ON %SCHEMA%.moderation_actions FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.assign_moderation_action_external_ref();

CREATE TRIGGER trg_audit_events_immutable BEFORE DELETE OR UPDATE ON %SCHEMA%.audit_events FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_audit_events_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.audit_events FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_audit_events_validate_entity BEFORE INSERT ON %SCHEMA%.audit_events FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.validate_audit_event_entity();

CREATE TRIGGER trg_automation_events_append_only BEFORE DELETE OR UPDATE ON %SCHEMA%.automation_events FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_automation_event_history();

CREATE TRIGGER trg_automation_policies_guard_scope BEFORE INSERT OR UPDATE ON %SCHEMA%.automation_policies FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_automation_policy_scope();

CREATE TRIGGER trg_automation_policies_prevent_delete BEFORE DELETE ON %SCHEMA%.automation_policies FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_automation_policies_set_updated_at BEFORE UPDATE ON %SCHEMA%.automation_policies FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_automation_policy_versions_guard BEFORE INSERT OR UPDATE ON %SCHEMA%.automation_policy_versions FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_automation_policy_version();

CREATE TRIGGER trg_automation_policy_versions_prevent_delete BEFORE DELETE ON %SCHEMA%.automation_policy_versions FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_automation_policy_versions_set_updated_at BEFORE UPDATE ON %SCHEMA%.automation_policy_versions FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_automation_run_step_attempts_guard BEFORE INSERT OR DELETE OR UPDATE ON %SCHEMA%.automation_run_step_attempts FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_automation_step_attempt();

CREATE TRIGGER trg_automation_run_steps_guard BEFORE INSERT OR UPDATE ON %SCHEMA%.automation_run_steps FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_automation_run_step();

CREATE TRIGGER trg_automation_run_steps_prevent_delete BEFORE DELETE ON %SCHEMA%.automation_run_steps FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_automation_run_steps_refresh_run AFTER INSERT OR UPDATE ON %SCHEMA%.automation_run_steps FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.refresh_automation_run();

CREATE TRIGGER trg_automation_run_steps_set_updated_at BEFORE UPDATE ON %SCHEMA%.automation_run_steps FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_automation_runs_guard_update BEFORE UPDATE ON %SCHEMA%.automation_runs FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_automation_run_update();

CREATE TRIGGER trg_automation_runs_prepare_insert BEFORE INSERT ON %SCHEMA%.automation_runs FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_automation_run_insert();

CREATE TRIGGER trg_automation_runs_prevent_delete BEFORE DELETE ON %SCHEMA%.automation_runs FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_automation_runs_set_updated_at BEFORE UPDATE ON %SCHEMA%.automation_runs FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_broadcast_attempts_guard BEFORE INSERT OR DELETE OR UPDATE ON %SCHEMA%.broadcast_attempts FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_broadcast_attempt();

CREATE TRIGGER trg_broadcast_campaigns_guard BEFORE INSERT OR UPDATE ON %SCHEMA%.broadcast_campaigns FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_broadcast_campaign();

CREATE TRIGGER trg_broadcast_campaigns_prevent_delete BEFORE DELETE ON %SCHEMA%.broadcast_campaigns FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_broadcast_campaigns_set_updated_at BEFORE UPDATE ON %SCHEMA%.broadcast_campaigns FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_broadcast_targets_prepare BEFORE INSERT OR UPDATE ON %SCHEMA%.broadcast_targets FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prepare_broadcast_target();

CREATE TRIGGER trg_broadcast_targets_prevent_delete BEFORE DELETE ON %SCHEMA%.broadcast_targets FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_broadcast_targets_refresh_campaign AFTER INSERT OR UPDATE ON %SCHEMA%.broadcast_targets FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.refresh_broadcast_campaign();

CREATE TRIGGER trg_broadcast_targets_set_updated_at BEFORE UPDATE ON %SCHEMA%.broadcast_targets FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_community_settings_guard_singleton BEFORE INSERT OR DELETE OR UPDATE ON %SCHEMA%.community_settings FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_community_settings_singleton();

CREATE TRIGGER trg_community_settings_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.community_settings FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_connected_chats_ensure_settings AFTER INSERT ON %SCHEMA%.connected_chats FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.ensure_connected_chat_settings();

CREATE TRIGGER trg_connected_chats_validate_chat_type BEFORE INSERT OR UPDATE OF chat_id ON %SCHEMA%.connected_chats FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.validate_connected_chat_chat_type();

CREATE TRIGGER trg_ensure_published_rule_acknowledgement BEFORE INSERT OR UPDATE ON %SCHEMA%.rule_acknowledgements FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.ensure_published_rule_acknowledgement();

CREATE TRIGGER trg_guard_rule_item_draft_only BEFORE INSERT OR DELETE OR UPDATE ON %SCHEMA%.rule_items FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_rule_item_draft_only();

CREATE TRIGGER trg_guard_rule_set_version_changes BEFORE INSERT OR DELETE OR UPDATE ON %SCHEMA%.rule_set_versions FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_rule_set_version_changes();

CREATE TRIGGER trg_join_requests_lifecycle BEFORE INSERT OR UPDATE ON %SCHEMA%.join_requests FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_join_request_lifecycle();

CREATE TRIGGER trg_join_requests_prevent_delete BEFORE DELETE ON %SCHEMA%.join_requests FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_join_requests_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.join_requests FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_actions_guard_update BEFORE UPDATE ON %SCHEMA%.moderation_actions FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_moderation_action_update();

CREATE TRIGGER trg_moderation_actions_prepare_insert BEFORE INSERT ON %SCHEMA%.moderation_actions FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prepare_moderation_action();

CREATE TRIGGER trg_moderation_actions_prevent_delete BEFORE DELETE ON %SCHEMA%.moderation_actions FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_actions_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.moderation_actions FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_actions_require_ban_evidence BEFORE INSERT OR UPDATE OF action_type, case_id, evidence_upload_id, action_origin ON %SCHEMA%.moderation_actions FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.enforce_moderation_ban_evidence();

CREATE TRIGGER trg_moderation_appeals_guard_ban BEFORE INSERT OR UPDATE OF action_id, appellant_user_id ON %SCHEMA%.moderation_appeals FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_appeal_ban_target();

CREATE TRIGGER trg_moderation_appeals_lifecycle BEFORE INSERT OR UPDATE ON %SCHEMA%.moderation_appeals FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_moderation_appeal_lifecycle();

CREATE TRIGGER trg_moderation_appeals_prevent_delete BEFORE DELETE ON %SCHEMA%.moderation_appeals FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_appeals_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.moderation_appeals FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_case_rules_prevent_delete BEFORE DELETE ON %SCHEMA%.moderation_case_rules FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_case_rules_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.moderation_case_rules FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_cases_guard_insert BEFORE INSERT ON %SCHEMA%.moderation_cases FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_moderation_case_insert();

CREATE TRIGGER trg_moderation_cases_guard_update BEFORE UPDATE ON %SCHEMA%.moderation_cases FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_moderation_case_update();

CREATE TRIGGER trg_moderation_cases_prevent_delete BEFORE DELETE ON %SCHEMA%.moderation_cases FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_cases_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.moderation_cases FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_cases_set_updated_at BEFORE UPDATE ON %SCHEMA%.moderation_cases FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_moderation_enforcement_attempts_guard BEFORE INSERT OR DELETE OR UPDATE ON %SCHEMA%.moderation_enforcement_attempts FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_moderation_enforcement_attempt();

CREATE TRIGGER trg_moderation_enforcement_attempts_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.moderation_enforcement_attempts FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_enforcement_runs_guard_update BEFORE UPDATE ON %SCHEMA%.moderation_enforcement_runs FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_moderation_enforcement_run_identity();

CREATE TRIGGER trg_moderation_enforcement_runs_prevent_delete BEFORE DELETE ON %SCHEMA%.moderation_enforcement_runs FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_enforcement_runs_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.moderation_enforcement_runs FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_enforcement_runs_set_updated_at BEFORE UPDATE ON %SCHEMA%.moderation_enforcement_runs FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_moderation_enforcement_targets_prepare BEFORE INSERT OR UPDATE ON %SCHEMA%.moderation_enforcement_targets FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prepare_moderation_enforcement_target();

CREATE TRIGGER trg_moderation_enforcement_targets_prevent_delete BEFORE DELETE ON %SCHEMA%.moderation_enforcement_targets FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_enforcement_targets_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.moderation_enforcement_targets FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_enforcement_targets_refresh_run AFTER INSERT OR UPDATE ON %SCHEMA%.moderation_enforcement_targets FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.refresh_moderation_enforcement_run();

CREATE TRIGGER trg_moderation_enforcement_targets_set_updated_at BEFORE UPDATE ON %SCHEMA%.moderation_enforcement_targets FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_moderation_evidence_items_guard BEFORE INSERT OR DELETE OR UPDATE ON %SCHEMA%.moderation_evidence_items FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_moderation_evidence_item();

CREATE TRIGGER trg_moderation_evidence_items_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.moderation_evidence_items FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_evidence_uploads_prevent_delete BEFORE DELETE ON %SCHEMA%.moderation_evidence_uploads FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_evidence_uploads_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.moderation_evidence_uploads FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_moderation_evidence_uploads_set_updated_at BEFORE UPDATE ON %SCHEMA%.moderation_evidence_uploads FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_moderation_evidence_uploads_validate BEFORE INSERT OR UPDATE ON %SCHEMA%.moderation_evidence_uploads FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.validate_moderation_evidence_upload();

CREATE TRIGGER trg_moderation_messages_append_only BEFORE DELETE OR UPDATE ON %SCHEMA%.moderation_messages FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_moderation_message_history();

CREATE TRIGGER trg_moderation_messages_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.moderation_messages FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_promotion_requests_lifecycle BEFORE INSERT OR UPDATE ON %SCHEMA%.promotion_requests FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_promotion_request_lifecycle();

CREATE TRIGGER trg_promotion_requests_prevent_delete BEFORE DELETE ON %SCHEMA%.promotion_requests FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_promotion_requests_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.promotion_requests FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_retention_policies_set_updated_at BEFORE UPDATE ON %SCHEMA%.retention_policies FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_role_assignments_guard_update BEFORE UPDATE ON %SCHEMA%.role_assignments FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_role_assignment_update();

CREATE TRIGGER trg_role_assignments_prepare_insert BEFORE INSERT ON %SCHEMA%.role_assignments FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prepare_role_assignment();

CREATE TRIGGER trg_role_assignments_prevent_delete BEFORE DELETE ON %SCHEMA%.role_assignments FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_role_assignments_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.role_assignments FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_role_definitions_guard_system BEFORE DELETE OR UPDATE ON %SCHEMA%.role_definitions FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_system_role_definition();

CREATE TRIGGER trg_role_definitions_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.role_definitions FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_rule_acknowledgements_append_only BEFORE DELETE OR UPDATE ON %SCHEMA%.rule_acknowledgements FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_rule_acknowledgement_history();

CREATE TRIGGER trg_rule_set_versions_set_updated_at BEFORE UPDATE ON %SCHEMA%.rule_set_versions FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_rule_sets_guard_identity BEFORE UPDATE ON %SCHEMA%.rule_sets FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_rule_set_identity();

CREATE TRIGGER trg_rule_sets_prevent_delete BEFORE DELETE ON %SCHEMA%.rule_sets FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_rule_sets_prevent_truncate BEFORE TRUNCATE ON %SCHEMA%.rule_sets FOR EACH STATEMENT EXECUTE FUNCTION %SCHEMA%.prevent_historical_record_delete();

CREATE TRIGGER trg_rule_sets_set_updated_at BEFORE UPDATE ON %SCHEMA%.rule_sets FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_scheduled_job_runs_guard BEFORE INSERT OR DELETE OR UPDATE ON %SCHEMA%.scheduled_job_runs FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_scheduled_job_run();

CREATE TRIGGER trg_scheduled_jobs_set_updated_at BEFORE UPDATE ON %SCHEMA%.scheduled_jobs FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON %SCHEMA%.chat_members FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON %SCHEMA%.chat_settings FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON %SCHEMA%.community_settings FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON %SCHEMA%.telegram_chats FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON %SCHEMA%.telegram_users FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON %SCHEMA%.user_settings FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.set_updated_at();

CREATE TRIGGER trg_telegram_chats_guard_chat_type BEFORE UPDATE OF chat_type ON %SCHEMA%.telegram_chats FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.guard_telegram_chat_type_change();

CREATE TRIGGER trg_validate_moderation_case_rule_scope BEFORE INSERT OR UPDATE ON %SCHEMA%.moderation_case_rules FOR EACH ROW EXECUTE FUNCTION %SCHEMA%.validate_moderation_case_rule_scope();
