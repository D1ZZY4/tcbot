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
