-- Amrith Sagar Voice Agent — Supabase schema (v1, with v2 billing tables)
-- Run once in the Supabase SQL editor. Safe to re-run (idempotent).
-- Every table carries tenant_id for v2 multi-tenancy.
--
-- Security model (v1): RLS is ENABLED on every table with NO policies (= deny-all for the anon/authenticated
-- roles). The frontend uses supabase-js ONLY for Auth. All data goes through FastAPI / agent / Celery, which
-- connect as the postgres role (pooler connection string) or with the service key, both of which bypass RLS.
--
-- No audio is recorded. Each call is stored as a JSON transcript (calls.transcript) and summarised for the
-- owner after the call (call_results.owner_summary).

create extension if not exists vector;
create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- helpers
create or replace function set_updated_at() returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

-- ---------------------------------------------------------------- tenants & users
create table if not exists tenants (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  city text,
  phone text,
  description text,                                   -- short company context typed at onboarding
  timezone text not null default 'Asia/Kolkata',
  languages text[] default array['kn-IN','en-IN','hi-IN','ta-IN','te-IN'],
  telephony_mode text not null default 'browser' check (telephony_mode in ('browser','phone')),
  onboarding_status text not null default 'created'
    check (onboarding_status in ('created','context_added','ready')),   -- ready = KB indexed
  created_at timestamptz default now()
);

-- one row per Supabase auth user (created automatically on signup; tenant linked at onboarding)
create table if not exists profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  tenant_id uuid references tenants(id),
  role text not null default 'business' check (role in ('admin','business')),
  display_name text,
  created_at timestamptz default now()
);

create or replace function handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (user_id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data->>'display_name', new.email))
  on conflict (user_id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function handle_new_user();

-- ---------------------------------------------------------------- agent configuration
create table if not exists agent_configs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  persona_name text not null default 'Amrutha',
  greeting_outbound text,
  greeting_inbound text,
  rules jsonb not null default '[]'::jsonb,          -- extra business rule strings appended to the prompt
  voices jsonb not null default '{}'::jsonb,         -- {"kn-IN": "<bulbul v4 flash speaker id>", ...}
  fillers jsonb not null default '{}'::jsonb,        -- {"check": {"en-IN": "...", "kn-IN": "..."}, "quote": {...}}
  tools_enabled text[] default array['search_knowledge_base','calculate_quote','check_availability',
                                     'create_tentative_booking','schedule_callback','record_answer','end_call'],
  prompt_version text not null default 'v1',
  max_call_seconds int not null default 480,          -- polite wrap-up, then hang up
  silence_timeout_seconds int not null default 20,
  is_active boolean default true,
  updated_at timestamptz default now()
);
create unique index if not exists agent_configs_one_active on agent_configs (tenant_id) where is_active;
drop trigger if exists agent_configs_updated on agent_configs;
create trigger agent_configs_updated before update on agent_configs for each row execute function set_updated_at();

-- dates the business has blocked manually (holidays, already fully booked offline)
create table if not exists blocked_dates (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  date date not null,
  reason text,
  created_at timestamptz default now(),
  unique (tenant_id, date)
);

-- ---------------------------------------------------------------- knowledge base
-- Embedding model: BAAI/bge-small-en-v1.5 (fastembed/ONNX, 384 dims). Chunks are embedded at ingest (onboarding / upload);
-- during calls only the short English query is embedded. Doc and query MUST use the same model; changing it = re-ingest.
create table if not exists kb_documents (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  file_name text not null,
  source text not null default 'upload' check (source in ('upload','onboarding_text','seed')),
  storage_path text,                                 -- kb-docs bucket path (null for pasted text)
  status text not null default 'uploaded' check (status in ('uploaded','processing','indexed','failed')),
  chunk_count int default 0,
  error text,
  uploaded_at timestamptz default now()
);

create table if not exists kb_chunks (
  id bigserial primary key,
  tenant_id uuid not null references tenants(id),
  document_id uuid references kb_documents(id) on delete cascade,
  doc_name text,
  section text,                                      -- heading path, e.g. "FAQs > Booking"
  content text not null,
  embedding vector(384),                             -- bge-small-en-v1.5, normalised, filled at ingest
  fts tsvector generated always as (to_tsvector('english', coalesce(section,'') || ' ' || content)) stored,
  created_at timestamptz default now()
);
create index if not exists kb_chunks_embedding_idx on kb_chunks using hnsw (embedding vector_cosine_ops);
create index if not exists kb_chunks_fts_idx on kb_chunks using gin (fts);
create index if not exists kb_chunks_tenant_idx on kb_chunks (tenant_id);

-- English keywords joined with OR ("jain food price" -> 'jain' | 'food' | 'price').
-- websearch_to_tsquery would AND every word and miss most chunks.
create or replace function kb_or_query(p_text text) returns tsquery
language sql immutable as $$
  select to_tsquery('english', coalesce(
    (select string_agg(w, ' | ')
       from regexp_split_to_table(lower(coalesce(p_text,'')), '[^a-z0-9]+') as w
      where length(w) > 1), ''));
$$;

-- Search used by the agent's search_knowledge_base tool.
-- p_query_embedding given   -> hybrid vector + keyword fused with reciprocal rank fusion (SEARCH_MODE=hybrid, default)
-- p_query_embedding = null  -> keyword-only (SEARCH_MODE=keyword, fallback / eval comparison)
create or replace function hybrid_search(
  p_tenant uuid,
  p_query_text text,
  p_query_embedding vector(384) default null,
  p_match_count int default 5,
  p_rrf_k int default 50
)
returns table (id bigint, section text, content text, doc_name text, score double precision)
language sql stable as $$
  with q as (select kb_or_query(p_query_text) as tsq),
  semantic as (
    select c.id, row_number() over (order by c.embedding <=> p_query_embedding) as rnk
    from kb_chunks c
    where p_query_embedding is not null
      and c.tenant_id = p_tenant
      and c.embedding is not null
    order by c.embedding <=> p_query_embedding
    limit p_match_count * 4
  ),
  keyword as (
    select c.id, row_number() over (order by ts_rank_cd(c.fts, q.tsq) desc) as rnk
    from kb_chunks c, q
    where c.tenant_id = p_tenant
      and c.fts @@ q.tsq
    order by ts_rank_cd(c.fts, q.tsq) desc
    limit p_match_count * 4
  )
  select c.id, c.section, c.content, c.doc_name,
         coalesce(1.0 / (p_rrf_k + s.rnk), 0) + coalesce(1.0 / (p_rrf_k + k.rnk), 0) as score
  from semantic s
  full outer join keyword k on s.id = k.id
  join kb_chunks c on c.id = coalesce(s.id, k.id)
  order by score desc
  limit p_match_count;
$$;

-- ---------------------------------------------------------------- customers, campaigns & jobs
create table if not exists customers (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  external_id text,                                   -- customer_id column from the CSV (e.g. C001)
  name text,
  phone text not null,
  language text,                                      -- preferred language, e.g. kn-IN
  token text unique not null default encode(gen_random_bytes(12), 'hex'),  -- personal call-page link /c/:token
  is_test boolean not null default false,
  created_at timestamptz default now(),
  unique (tenant_id, phone)
);

create table if not exists campaigns (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  name text not null,
  type text not null check (type in ('post_event_feedback','enquiry_followup','pre_event_confirmation')),
  questions jsonb not null default '[]'::jsonb,          -- copied from backend/data/campaign_types.json at creation, editable
  call_window_start time default '10:00',                -- interpreted in tenants.timezone (IST)
  call_window_end time default '20:00',
  status text not null default 'draft' check (status in ('draft','running','paused','completed','cancelled')),
  digest jsonb,                                          -- owner digest of the whole campaign, written when it completes
  digest_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
drop trigger if exists campaigns_updated on campaigns;
create trigger campaigns_updated before update on campaigns for each row execute function set_updated_at();

-- The DB is the queue's source of truth. Celery beat `campaign_tick` picks the next due job; Celery only executes.
create table if not exists call_jobs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  campaign_id uuid references campaigns(id) on delete cascade,
  customer_id uuid not null references customers(id),
  customer jsonb not null,                               -- snapshot of the CSV row at upload time
  status text not null default 'queued'
    check (status in ('queued','ringing','in_call','completed','no_answer','declined','failed','cancelled')),
  attempts int not null default 0,
  max_attempts int not null default 3,
  next_attempt_at timestamptz not null default now(),
  room_name text,
  ring_started_at timestamptz,                           -- server owns the 30 s ring timeout
  celery_task_id text,
  last_error text,
  is_test boolean not null default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index if not exists call_jobs_campaign_idx on call_jobs (campaign_id, status);
create index if not exists call_jobs_due_idx on call_jobs (status, next_attempt_at);
drop trigger if exists call_jobs_updated on call_jobs;
create trigger call_jobs_updated before update on call_jobs for each row execute function set_updated_at();

-- ---------------------------------------------------------------- calls, turns, tool calls, results
-- One row per attempt, including unanswered ones (outcome no_answer / declined), so retry stats work.
create table if not exists calls (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  job_id uuid references call_jobs(id),
  customer_id uuid references customers(id),
  direction text not null check (direction in ('outbound','inbound')),
  call_type text,                                        -- post_event_feedback | enquiry_followup | pre_event_confirmation | inbound
  room_name text,
  language_initial text,
  languages_used text[],
  prompt_version text,
  started_at timestamptz,
  answered_at timestamptz,
  ended_at timestamptz,
  duration_sec int,
  outcome text check (outcome in ('completed','no_answer','declined','dropped','transferred','error')),
  ended_by text check (ended_by in ('agent','customer','silence','max_duration','timeout','error','balance')),
  transcript jsonb not null default '[]'::jsonb,         -- [{"i":0,"speaker":"agent","text":"...","lang":"kn-IN","t":1.2}]
  live_answers jsonb not null default '{}'::jsonb,       -- {"food_rating": "5 - loved the holige", ...} from record_answer
  stt_seconds numeric default 0,
  tts_characters int default 0,
  llm_input_tokens int default 0,
  llm_cached_tokens int default 0,
  llm_output_tokens int default 0,
  api_cost_inr numeric(10,4),
  is_test boolean not null default false,
  created_at timestamptz default now()
);
create index if not exists calls_tenant_time_idx on calls (tenant_id, started_at desc);
create index if not exists calls_job_idx on calls (job_id);

create table if not exists turns (
  id bigserial primary key,
  call_id uuid not null references calls(id) on delete cascade,
  turn_index int not null,
  speaker text not null check (speaker in ('agent','customer')),
  text text,
  language text,
  -- latency parts, filled on agent turns (definitions in docs/api_contracts.md -> Latency definitions)
  eou_delay_ms int,               -- customer stopped speaking -> final transcript / end of turn decided
  llm_ttft_ms int,
  tts_ttfb_ms int,
  total_response_ms int,          -- customer end-of-speech -> first agent audio frame (eou + ttft + ttfb)
  interrupted boolean default false,
  created_at timestamptz default now()
);
create index if not exists turns_call_idx on turns (call_id, turn_index);

create table if not exists tool_calls (
  id bigserial primary key,
  call_id uuid not null references calls(id) on delete cascade,
  turn_index int,
  name text not null,
  args jsonb,
  result jsonb,
  duration_ms int,
  ok boolean,
  created_at timestamptz default now()
);
create index if not exists tool_calls_call_idx on tool_calls (call_id);

create table if not exists call_results (
  call_id uuid primary key references calls(id) on delete cascade,
  tenant_id uuid not null references tenants(id),
  extracted jsonb,                       -- English fields per backend/data/campaign_types.json -> extraction_fields
  owner_summary jsonb,                   -- what the owner reads (English): headline, key points, action items (docs/prompts.md §2)
  transcript_en jsonb,                   -- English translation of non-English turns: [{"i":1,"text_en":"..."}]
  owner_summary_native jsonb,            -- v2: same summary in the owner's language/script (sarvam-105b)
  questions_total int,
  questions_answered int,
  extraction_valid boolean,
  extract_model text,
  judge_scores jsonb,                    -- {"naturalness":{"score":4,"why":"..."}, ...}
  judge_model text,
  flags text[] default '{}',             -- hallucination, policy_break, no_disclosure, complaint, off_topic, slow
  callback_needed boolean default false,
  synced_to_sheet boolean default false,
  created_at timestamptz default now()
);

-- ---------------------------------------------------------------- bookings & callbacks
create table if not exists bookings (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  call_id uuid references calls(id),
  customer_id uuid references customers(id),
  customer_name text,
  phone text,
  event_type text,
  event_date date not null,
  venue_area text,
  zone int,
  guests int not null,
  package_code text,
  notes text,
  quote_amount numeric(12,2),
  status text not null default 'tentative' check (status in ('tentative','confirmed','expired','cancelled')),
  hold_until timestamptz,                -- reservation hold = created + 48h (agent says "reserved under your name", never "confirmed")
  advance_amount numeric(12,2),          -- 40% of quote_amount, computed in Python
  payment_link_id text,                  -- Razorpay Payment Link id (test mode in v1)
  payment_link_url text,
  payment_status text not null default 'not_sent'
    check (payment_status in ('not_sent','link_sent','paid','expired','failed')),
  paid_at timestamptz,
  calendar_event_id text,                -- Google Calendar event mirroring this booking
  is_test boolean not null default false,
  created_at timestamptz default now()
);
create index if not exists bookings_date_idx on bookings (tenant_id, event_date, status);

create table if not exists callbacks (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  call_id uuid references calls(id),
  customer_id uuid references customers(id),
  customer_name text,
  phone text,
  reason text not null,
  preferred_time text,
  status text not null default 'open' check (status in ('open','done')),
  is_test boolean not null default false,
  created_at timestamptz default now()
);

-- ---------------------------------------------------------------- evaluation (simulated callers, text mode)
create table if not exists eval_runs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  prompt_version text not null,
  live_llm text,
  sim_llm text,
  judge_llm text,
  search_mode text,                      -- keyword | hybrid
  personas_count int,
  notes text,
  started_at timestamptz default now(),
  finished_at timestamptz
);

create table if not exists eval_results (
  id bigserial primary key,
  run_id uuid not null references eval_runs(id) on delete cascade,
  persona_id int not null,
  persona_name text,
  turns int,
  transcript jsonb,
  tool_log jsonb,
  judge_scores jsonb,
  flags text[] default '{}',
  expected_check_passed boolean,         -- persona-specific assertion, e.g. quote == 375500
  created_at timestamptz default now()
);

-- ---------------------------------------------------------------- billing (v2 demo)
create table if not exists wallets (
  tenant_id uuid primary key references tenants(id),
  balance_seconds int not null default 0,
  low_balance_alert_pct int default 10,
  auto_topup boolean default false,
  updated_at timestamptz default now()
);

create table if not exists payments (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  razorpay_order_id text,
  razorpay_payment_id text,
  amount_inr numeric(12,2) not null,
  minutes int not null,
  plan text,
  status text not null default 'created' check (status in ('created','paid','failed')),
  created_at timestamptz default now()
);

create table if not exists usage_ledger (            -- append-only
  id bigserial primary key,
  tenant_id uuid not null references tenants(id),
  call_id uuid references calls(id),
  seconds int not null,
  billed_amount_inr numeric(10,4),
  api_cost_inr numeric(10,4),
  created_at timestamptz default now()
);

create table if not exists pricing_rates (
  id serial primary key,
  provider text not null,              -- sarvam_stt, sarvam_tts_v4_flash, sarvam_llm_in, sarvam_llm_cached, sarvam_llm_out, plivo_india
  unit text not null,                  -- per_minute, per_1000_chars, per_1m_tokens
  rate_inr numeric(12,4) not null,
  valid_from date not null default '2026-11-01',
  unique (provider, valid_from)
);

insert into pricing_rates (provider, unit, rate_inr) values
  ('sarvam_stt', 'per_minute', 0.49),
  ('sarvam_tts_v4_flash', 'per_1000_chars', 1.00),
  ('sarvam_llm_in', 'per_1m_tokens', 15),
  ('sarvam_llm_cached', 'per_1m_tokens', 5),
  ('sarvam_llm_out', 'per_1m_tokens', 60),
  ('plivo_india', 'per_minute', 0.38)
on conflict (provider, valid_from) do nothing;

-- ---------------------------------------------------------------- RLS: deny-all for anon/authenticated
do $$
declare t text;
begin
  foreach t in array array[
    'tenants','profiles','agent_configs','blocked_dates','kb_documents','kb_chunks','customers','campaigns',
    'call_jobs','calls','turns','tool_calls','call_results','bookings','callbacks','eval_runs','eval_results',
    'wallets','payments','usage_ledger','pricing_rates']
  loop
    execute format('alter table %I enable row level security', t);
  end loop;
end $$;
-- v2: add per-tenant policies using profiles.tenant_id = auth.uid()'s tenant.

-- ---------------------------------------------------------------- seed: the one v1 tenant
insert into tenants (id, name, city, phone, description, onboarding_status)
values ('00000000-0000-0000-0000-000000000001', 'Amrith Sagar Catering', 'Bengaluru', '9108820437',
        'Family catering business in Bengaluru since 1956: weddings, family functions, corporate events across Karnataka.',
        'context_added')
on conflict (id) do nothing;

insert into agent_configs (tenant_id, persona_name, voices, fillers)
select '00000000-0000-0000-0000-000000000001', 'Amrutha',
       -- Bulbul v4 Flash speaker IDs from the Sarvam Voices page (verify by listening; see docs/sarvam_stack.md §5)
       '{"kn-IN": "chaitra_kn_conversation", "hi-IN": "chaitra_hi_customer", "en-IN": "ishita_en_customer",
         "te-IN": "kavitha_te_conversation", "ta-IN": "gokul_ta_narration"}'::jsonb,
       '{"check":   {"en-IN": "One second, let me check that for you."},
         "booking": {"en-IN": "Okay, I am noting the booking now."}}'::jsonb
where not exists (select 1 from agent_configs where tenant_id = '00000000-0000-0000-0000-000000000001' and is_active);

insert into wallets (tenant_id, balance_seconds)
values ('00000000-0000-0000-0000-000000000001', 60000)
on conflict (tenant_id) do nothing;

-- After your first signup, link yourself to the tenant (run once, replace the email):
-- update profiles set tenant_id = '00000000-0000-0000-0000-000000000001', role = 'admin'
--  where user_id = (select id from auth.users where email = 'you@example.com');
