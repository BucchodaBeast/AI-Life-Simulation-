"""
society/config.py — all tunables for Signal Society V2 ("the Society").

Everything is env-driven so you can change behaviour from the Render dashboard
without touching code. SOC_ENABLED=0 (default) keeps the whole thing dormant:
no scheduler job, no LLM calls, no DB writes. That is your kill switch.
"""
import os


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


def _float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def enabled() -> bool:
    return os.environ.get('SOC_ENABLED', '0').strip() == '1'


# ── pacing ────────────────────────────────────────────────────────────────────
TICK_MINUTES     = _int('SOC_TICK_MINUTES', 20)     # how often the world advances
AGENTS_PER_TICK  = _int('SOC_AGENTS_PER_TICK', 2)   # how many citizens act per tick
POP_CAP          = _int('SOC_POP_CAP', 9)           # living population cap
SEASON_HOURS     = _int('SOC_SEASON_HOURS', 48)     # how often selection / birth runs
MIN_AGE_TICKS    = _int('SOC_MIN_AGE_TICKS', 20)    # ticks before a citizen can parent / be retired
PASSIVE_REGEN    = _int('SOC_PASSIVE_REGEN', 3)     # energy regained per tick by everyone

# ── energy costs (each action drains energy; resting restores it) ─────────────
COST = {
    'search': 15, 'message': 5, 'respond': 4, 'review': 10,
    'innovate': 25, 'gene_swap': 8, 'rest': 0,
}
REST_GAIN = 30

# ── world constants ───────────────────────────────────────────────────────────
DOMAINS = ['health', 'agriculture', 'economy', 'technology',
           'environment', 'energy', 'governance', 'education']

DOMAIN_TITLES = {
    'health': 'Public Health Analyst',
    'agriculture': 'Agronomist',
    'economy': 'Economist',
    'technology': 'Technologist',
    'environment': 'Environmental Scientist',
    'energy': 'Energy Analyst',
    'governance': 'Policy Analyst',
    'education': 'Education Researcher',
}

PROFESSION_MIN_REVIEWED = 4      # reviewed findings needed before a profession can form
PROFESSION_MIN_SHARE    = 0.5    # share of reviewed work that must sit in one domain
INNOVATION_MIN_FINDINGS = 3      # reviewed findings in-domain before innovating
INNOVATION_COOLDOWN_H   = 24
REVIEWS_NEEDED          = 2      # peer reviews before a finding counts as "reviewed"

MAX_AFFINITY = 10.0

# ── LLM provider settings (see llm.py) ────────────────────────────────────────
# Model ids are discovered and verified at runtime (providers retire models often).
# Set SOC_FAST_MODEL / SOC_GROQ_SMART_MODEL / SOC_GEMINI_MODEL / SOC_OPENROUTER_MODEL to pin one.


def admin_token() -> str:
    return os.environ.get('SOC_ADMIN_TOKEN', '').strip()
