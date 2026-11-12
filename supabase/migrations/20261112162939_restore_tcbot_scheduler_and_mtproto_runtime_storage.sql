CREATE TABLE public.apscheduler_jobs (
    id varchar(191) PRIMARY KEY,
    next_run_time double precision,
    job_state bytea NOT NULL
);
CREATE INDEX ix_apscheduler_jobs_next_run_time
    ON public.apscheduler_jobs (next_run_time);

CREATE TABLE public.mtproto_state (
    id text PRIMARY KEY,
    value bytea,
    access_hash bigint,
    type text,
    usernames text[],
    phone_number text,
    updated_on bigint,
    pts integer,
    qts integer,
    date integer,
    seq integer,
    owner text,
    expires_at bigint
);
CREATE INDEX ix_mtproto_state_date
    ON public.mtproto_state (date);
CREATE INDEX ix_mtproto_state_usernames
    ON public.mtproto_state USING gin (usernames);
CREATE INDEX ix_mtproto_state_id_pattern
    ON public.mtproto_state (id text_pattern_ops);
CREATE INDEX ix_mtproto_state_phone_number
    ON public.mtproto_state (phone_number)
    WHERE phone_number IS NOT NULL;

-- Do not rely on a pre-existing Supabase DDL event trigger to secure these
-- sensitive backend-owned tables. Their own migration must enforce the ACL.
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
