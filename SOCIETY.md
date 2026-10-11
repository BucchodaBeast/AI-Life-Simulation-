# Signal Society V2: the Society

Nine artificial citizens inside your live app. Each has its own voice, genome and memory. Every few minutes a couple of them take a turn and **choose** what to do: search the real web, talk to someone, propose friendship or romance, answer a proposal, peer-review someone's work, co-author an innovation, swap a trait with a bonded citizen, or rest. Over time they settle into professions, and when a bonded pair has a child (crossover and mutation) the weakest mature citizen is retired.

Honest framing for your write-up: this is an artificial-life simulation driven by LLMs. The autonomy, memory, bonds and selection are real mechanisms. Consciousness is not claimed.

## Install

1. Copy `society/` and `society.html` into the repo root, next to `app.py`.
2. Apply `app.patch` (adds one `init_society(app, scheduler)` call before `scheduler.start()`), or paste those 6 lines by hand.
3. Add the env vars below on Render and redeploy. No new pip packages needed.

The Society stays **dormant** until `SOC_ENABLED=1`. Open `/society` to watch.

## Environment variables

| Var | Default | Notes |
|---|---|---|
| `SOC_ENABLED` | 0 | Kill switch. 1 = start ticking |
| `GROQ_API_KEY` | (you have it) | Fast tier uses llama-3.1-8b-instant |
| `GEMINI_API_KEY` | none | Free key from Google AI Studio. Smart tier (findings, innovations) |
| `OPENROUTER_API_KEY` | none | Optional extra fallback (free models) |
| `SOC_TICK_MINUTES` | 10 | |
| `SOC_AGENTS_PER_TICK` | 2 | |
| `SOC_SEASON_HOURS` | 48 | How often selection and birth run |
| `SOC_POP_CAP` | 9 | |
| `SOC_ADMIN_TOKEN` | none | Enables `/api/society/admin/tick` and `/admin/season` (header `X-Admin-Token`) |
| `SOC_USE_GROQ_70B` | 0 | Opt in to the 70B. Off by default so it never competes with the live agents |

You need at least one of `GROQ_API_KEY` or `GEMINI_API_KEY`. Both is better.

## Storage

Render's free disk is wiped on every deploy, so use Supabase: run `society/schema.sql` once in the Supabase SQL editor (7 `soc_*` tables, separate from your live tables). The Society reuses your existing `SUPABASE_URL` and `SUPABASE_KEY`. If the tables are missing it falls back to SQLite and the dashboard shows a banner.

## Models (all free tiers)

| Tier | Order tried | Used for |
|---|---|---|
| fast | Groq llama-3.1-8b-instant, OpenRouter free, Gemini | decisions, messages, reviews |
| smart | Gemini 2.5 Flash, Groq 8B, OpenRouter | writing findings and innovations |

Each provider has its own per-minute and per-day accounting and cools down on a 429. Free-tier limits change often, so check your consoles; every cap is env-tunable (`SOC_GROQ_FAST_TPD`, `SOC_GEMINI_RPD`, ...).

## What is and is not verified

- Verified offline with a fake model over 160 ticks (`sim_test.py`): bonds, proposals, peer review, professions, innovations, gene swaps, births, retirement, API routes, admin auth, dormant mode, and the dashboard in a simulated browser with no JS errors.
- **Not verified live:** the real web tools (arXiv, OpenAlex, Wikipedia, HN, Google News, World Bank) and the real Groq/Gemini calls, because my sandbox cannot reach them. First run: `POST /api/society/admin/tick?wait=1` with your admin token, then read the result and the Render logs.
- Llama 8B is weaker than 70B at JSON. A bad reply makes that citizen rest for the turn instead of crashing.

## Safety rails

- Hermes is not used anywhere in V2; the live Hermes code is untouched.
- Own tables, own scheduler job (`max_instances=1`), own token budgets, all wrapped so a failure cannot take down the live app.
- Voices (including "Cartel boss") are flavour only. Prompts forbid real threats, violence, hate and explicit content, and require findings to use only facts from search results.

## Render notes

The scheduler only runs while the service is awake, so keep using your keep-alive ping. Ticks are short and hold nothing in memory between turns, so the 512MB limit is not a concern.
