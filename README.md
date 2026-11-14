# Amrith Sagar Voice Calling Agent: starter pack

Context and specs for building the project from scratch with Claude Code. Business data is synthetic. In v1, calls are simulated over WebRTC in the browser. The production path (Plivo SIP) is documented for v1.5. Calls are stored as JSON transcripts with an LLM-written owner summary; no audio is recorded.

## What's inside
| File | Purpose |
|---|---|
| `CLAUDE.md` | Project context Claude Code reads automatically: goals, fixed stack, repo layout, verified Sarvam/LiveKit facts, design rules |
| `docs/build_plan.md` | Milestones 0–10 (plus 2.5 and 7.5) with tasks and acceptance criteria |
| `docs/architecture.md` | System design: flows, onboarding, dashboards, metrics, security, billing, v1.5 Plivo, v2 optimizations |
| `docs/knowledge_base.md` | Amrith Sagar business knowledge (ingested into pgvector at onboarding) |
| `docs/prompts.md` | Live agent prompt template, extraction + owner summary prompt, campaign digest, judge rubric, 25 test personas |
| `docs/api_contracts.md` | Agent metadata, lifecycle, transcript format, tool signatures, REST endpoints, Celery tasks, Redis channels, metric SQL |
| `docs/sarvam_stack.md` | Every Sarvam module (STT, LLM, TTS, translate, transliterate, LID, batch): which model, which API, when, and how it runs inside LiveKit; voices; costs; spike checklist |
| `docs/review_and_task_list.md` | Spec review (2026-11-12): what was fixed and why, plus the ordered task list |
| `docs/archive/` | Superseded documents kept for reference |
| `supabase/schema.sql` | Supabase schema: RLS, pgvector, keyword/hybrid search function, seed tenant (idempotent) |
| `backend/data/amrith_sagar_pricing.json` | Pricing and quote rules, the source of truth for the quote tool |
| `backend/data/areas.json` | Area → zone lookup with aliases |
| `backend/data/campaign_types.json` | Per call type: questions, prompt block, extraction fields, Sheet columns, owner summary fields |
| `backend/data/sample_customers.csv` | 12 synthetic customers for the three campaigns |
| `backend/` | All Python: `app/` (FastAPI, layered routers → services → repos → db, plus core/ and schemas/), `agent/` (LiveKit worker), `worker/` (Celery), `evals/`, `scripts/` (`check_env.py`), `tests/`, `requirements*` |
| `frontend/` | React + JavaScript (Vite) app; `frontend/README.md` shows the src layout, `frontend/.env.example` the public env vars |
| `.env.example`, `docker-compose.yml` | Backend config (copy to `.env` at the repo root), Redis |

## Layout
```
Voice-Agent/
├── backend/    # all Python (run Python commands from here)
├── frontend/   # React JS (Vite)
├── supabase/   # schema.sql
├── docs/
├── secrets/    # git-ignored
└── .env        # git-ignored
```

## How to start
1. `git init` in this folder (`.env` and `secrets/` are already git-ignored).
2. Do the manual account setup in `docs/build_plan.md` → Milestone 0 and fill `.env` from `.env.example`. Use the Supabase **session pooler** connection string.
3. Run `supabase/schema.sql` in the Supabase SQL editor.
4. Check every connection: `.venv\Scripts\activate`, then `cd backend`, then `python scripts/check_env.py`.
5. Open the folder in Claude Code and say:
   > Read CLAUDE.md and docs/build_plan.md. Implement Milestone 0, then stop and tell me how to verify it.
6. Continue milestone by milestone (`Implement Milestone 1`, …).
