ALTER TABLE public.apscheduler_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public.apscheduler_jobs
FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLE public.apscheduler_jobs TO service_role;

ALTER TABLE public.mtproto_state ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public.mtproto_state
FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLE public.mtproto_state TO service_role;
