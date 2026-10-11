"""
society/llm.py — multi-model gateway for the Society (free tiers).

Why this file discovers models instead of hardcoding them: providers retire models
constantly (Groq shut down llama-3.1-8b-instant and llama-3.3-70b-versatile for free tiers on
2026-08-16; Google stopped serving gemini-2.5-flash to new users). Every provider here:
  1. uses a pinned model if you set the env var (SOC_FAST_MODEL, SOC_GROQ_SMART_MODEL,
     SOC_GEMINI_MODEL, SOC_OPENROUTER_MODEL),
  2. otherwise tries sensible defaults, then asks the provider's /models endpoint what exists,
  3. treats a 404 as "this model is gone" — remembers it for 6 hours and tries the next one.
The working model is cached, so normal calls cost one request.

Tiers
  fast  — decisions, messages, reviews.      Groq gpt-oss-20b first.
  smart — findings and innovations.          Gemini (newest flash) first, then Groq gpt-oss-120b.

Each provider has its own per-minute / per-day accounting and cools down on 429s.
Providers without a key are skipped. Visit /api/society/admin/diag (with X-Admin-Token) to
see exactly which models each provider accepts right now.
"""
import os, re, json, time, threading, logging
from collections import deque
from datetime import datetime, timezone
import requests

log = logging.getLogger('society.llm')
_lock = threading.Lock()
_mock = None   # tests can install a fake: fn(task, system, user) -> str

GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'
GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta'
BAD_TTL = 6 * 3600
DISC_TTL = 6 * 3600


def set_mock(fn):
    global _mock
    _mock = fn


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _groq_keys():
    keys = [os.environ.get('GROQ_API_KEY', '')]
    keys += [os.environ.get(f'GROQ_API_KEY_{i}', '') for i in range(2, 6)]
    return [k for k in keys if k]


def _env_key(name):
    return lambda: [os.environ.get(name, '')] if os.environ.get(name) else []


def _groq_smart_keys():
    flag = os.environ.get('SOC_USE_GROQ_SMART', os.environ.get('SOC_USE_GROQ_70B', '1'))
    return _groq_keys() if flag == '1' else []


# Limits are conservative guesses for free tiers (they change — check your consoles; all env-tunable).
PROVIDERS = {
    'groq_fast': dict(kind='openai', url=GROQ_URL, keys=_groq_keys, env_model='SOC_FAST_MODEL',
                      defaults=['openai/gpt-oss-20b'], prefer=['gpt-oss-20b', 'gpt-oss-120b'], reasoning_effort=True,
                      rpm=_int('SOC_GROQ_RPM', 20), tpm=_int('SOC_GROQ_TPM', 6000),
                      tpd=_int('SOC_GROQ_FAST_TPD', 170000), rpd=_int('SOC_GROQ_FAST_RPD', 900)),
    'groq_smart': dict(kind='openai', url=GROQ_URL, keys=_groq_smart_keys, env_model='SOC_GROQ_SMART_MODEL',
                       defaults=['openai/gpt-oss-120b'], prefer=['gpt-oss-120b', 'gpt-oss-20b'], reasoning_effort=True,
                       rpm=_int('SOC_GROQ_SMART_RPM', 15), tpm=_int('SOC_GROQ_SMART_TPM', 6000),
                       tpd=_int('SOC_GROQ_SMART_TPD', 170000), rpd=_int('SOC_GROQ_SMART_RPD', 900)),
    'gemini': dict(kind='gemini', keys=_env_key('GEMINI_API_KEY'), env_model='SOC_GEMINI_MODEL', defaults=[],
                   rpm=_int('SOC_GEMINI_RPM', 8), tpm=_int('SOC_GEMINI_TPM', 200000),
                   tpd=_int('SOC_GEMINI_TPD', 600000), rpd=_int('SOC_GEMINI_RPD', 180)),
    'nvidia': dict(kind='openai', url='https://integrate.api.nvidia.com/v1/chat/completions',
                   keys=_env_key('NVIDIA_API_KEY'), env_model='SOC_NVIDIA_MODEL',
                   defaults=['openai/gpt-oss-120b'],
                   prefer=['gpt-oss-120b', 'llama-3.3-70b-instruct', 'nemotron-3-super', 'mistral-small', 'qwen'],
                   rpm=_int('SOC_NVIDIA_RPM', 30), tpm=_int('SOC_NVIDIA_TPM', 60000),
                   tpd=_int('SOC_NVIDIA_TPD', 600000), rpd=_int('SOC_NVIDIA_RPD', 1500)),
    'mistral': dict(kind='openai', url='https://api.mistral.ai/v1/chat/completions',
                    keys=_env_key('MISTRAL_API_KEY'), env_model='SOC_MISTRAL_MODEL',
                    defaults=['mistral-small-latest'],
                    prefer=['mistral-small', 'mistral-medium', 'mistral-large'],
                    rpm=_int('SOC_MISTRAL_RPM', 40), tpm=_int('SOC_MISTRAL_TPM', 100000),
                    tpd=_int('SOC_MISTRAL_TPD', 400000), rpd=_int('SOC_MISTRAL_RPD', 2000)),
    'cerebras': dict(kind='openai', url='https://api.cerebras.ai/v1/chat/completions',
                     keys=_env_key('CEREBRAS_API_KEY'), env_model='SOC_CEREBRAS_MODEL',
                     defaults=['gpt-oss-120b'], prefer=['gpt-oss-120b', 'qwen'], reasoning_effort=True,
                     rpm=_int('SOC_CEREBRAS_RPM', 25), tpm=_int('SOC_CEREBRAS_TPM', 50000),
                     tpd=_int('SOC_CEREBRAS_TPD', 500000), rpd=_int('SOC_CEREBRAS_RPD', 1000)),
    # OpenRouter's free models are capped at ~50 requests/day until you buy $10 of credit: emergency spare only.
    'openrouter': dict(kind='openai', url='https://openrouter.ai/api/v1/chat/completions',
                       keys=_env_key('OPENROUTER_API_KEY'), env_model='SOC_OPENROUTER_MODEL',
                       defaults=['openai/gpt-oss-120b:free', 'openrouter/free'], no_discovery=True,
                       rpm=_int('SOC_OPENROUTER_RPM', 15), tpm=60000,
                       tpd=_int('SOC_OPENROUTER_TPD', 150000), rpd=_int('SOC_OPENROUTER_RPD', 45)),
}

CHAINS = {
    'fast':  ['groq_fast', 'nvidia', 'cerebras', 'mistral', 'groq_smart', 'gemini', 'openrouter'],
    'smart': ['gemini', 'groq_smart', 'nvidia', 'mistral', 'cerebras', 'groq_fast', 'openrouter'],
}

_state = {n: dict(req=deque(), tok=deque(), day='', day_tokens=0, day_reqs=0,
                  cooldown=0.0, ok=0, err=0, last_error='') for n in PROVIDERS}
_ms = {n: dict(active=None, bad={}, discovered=[], disc_ts=0.0) for n in PROVIDERS}
_key_idx = {'groq': 0}


# ── accounting ───────────────────────────────────────────────────────────────
def _today():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _reset_day(st):
    t = _today()
    if st['day'] != t:
        st['day'], st['day_tokens'], st['day_reqs'] = t, 0, 0


def _available(name, est):
    cfg, st, now = PROVIDERS[name], _state[name], time.time()
    if not cfg['keys']():
        return False
    _reset_day(st)
    if now < st['cooldown']:
        return False
    if st['day_tokens'] + est > cfg['tpd'] or st['day_reqs'] >= cfg['rpd']:
        return False
    while st['req'] and st['req'][0] < now - 60:
        st['req'].popleft()
    while st['tok'] and st['tok'][0][0] < now - 60:
        st['tok'].popleft()
    if len(st['req']) >= cfg['rpm']:
        return False
    if sum(t for _, t in st['tok']) + est > cfg['tpm']:
        return False
    return True


def _daily_ok(name, est):
    cfg, st = PROVIDERS[name], _state[name]
    _reset_day(st)
    return st['day_tokens'] + est <= cfg['tpd'] and st['day_reqs'] < cfg['rpd']


def _reserve(name, est):
    st, now = _state[name], time.time()
    st['req'].append(now)
    st['tok'].append((now, est))
    st['day_reqs'] += 1
    st['day_tokens'] += est


def _settle(name, est, actual):
    _state[name]['day_tokens'] += max(0, actual - est)


# ── json helper ──────────────────────────────────────────────────────────────
def extract_json(text):
    """Pull a JSON object out of a model reply (handles fences / chatter)."""
    if not text:
        return None
    t = text.replace('```json', '').replace('```', '').strip()
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except Exception:
        pass
    s, e = t.find('{'), t.rfind('}')
    if s >= 0 and e > s:
        try:
            v = json.loads(t[s:e + 1])
            return v if isinstance(v, dict) else None
        except Exception:
            return None
    return None


# ── model discovery ──────────────────────────────────────────────────────────
def _pick_key(name):
    keys = PROVIDERS[name]['keys']()
    if not keys:
        return ''
    if name.startswith('groq'):
        _key_idx['groq'] = (_key_idx['groq'] + 1) % len(keys)
        return keys[_key_idx['groq']]
    return keys[0]


_GEMINI_SKIP = ('image', 'tts', 'live', 'audio', 'native', 'embed', 'thinking', 'exp', 'robotics',
                'computer', 'customtools', 'deep-research', 'learnlm', 'gemma', 'aqa', 'veo', 'imagen')
_OPENAI_SKIP = ('whisper', 'tts', 'orpheus', 'guard', 'safeguard', 'safety', 'embed', 'rerank', 'compound', 'distil',
                'vision', '-vl', 'vl-', 'reward', 'clip', 'parakeet', 'moderation', 'ocr', 'image', 'audio', 'speech',
                'transcri', 'diffusion', 'allam')


def _gemini_rank(mid):
    m = re.match(r'gemini-(\d+(?:\.\d+)?)', mid)
    ver = float(m.group(1)) if m else 0.0
    # newest version first; stable before preview; full flash before flash-lite
    return (-ver, 'preview' in mid, 'lite' in mid, mid)


def _discover(name):
    """Ask the provider which chat models exist for this key. Never raises."""
    cfg, ms = PROVIDERS[name], _ms[name]
    ms['disc_ts'] = time.time()
    try:
        if cfg['kind'] == 'gemini':
            r = requests.get(f'{GEMINI_BASE}/models', params={'pageSize': 200},
                             headers={'x-goog-api-key': _pick_key(name)}, timeout=20)
            r.raise_for_status()
            ids = [m['name'].split('/', 1)[1] for m in r.json().get('models', [])
                   if 'generateContent' in m.get('supportedGenerationMethods', [])]
            keep = [i for i in ids if i.startswith('gemini-') and 'flash' in i and not any(x in i for x in _GEMINI_SKIP)]
            ms['discovered'] = sorted(keep, key=_gemini_rank)[:8]
        elif cfg['kind'] == 'openai' and not cfg.get('no_discovery'):
            r = requests.get(cfg['url'].replace('/chat/completions', '/models'),
                             headers={'Authorization': f'Bearer {_pick_key(name)}'}, timeout=20)
            r.raise_for_status()
            ids = [m['id'] for m in r.json().get('data', []) if m.get('active', True) and m.get('id')]
            keep = [i for i in ids if not any(x in i.lower() for x in _OPENAI_SKIP)]
            prefer = cfg.get('prefer', [])
            rank = lambda i: (next((n for n, p in enumerate(prefer) if p in i.lower()), len(prefer)), i)
            ms['discovered'] = sorted(keep, key=rank)[:8]
        log.info(f'{name}: discovered models {ms["discovered"]}')
    except Exception as e:
        log.warning(f'{name}: model discovery failed — {type(e).__name__}: {str(e)[:140]}')


def _ensure_discovered(name):
    ms = _ms[name]
    if not ms['discovered'] and time.time() - ms['disc_ts'] > (60 if not ms['disc_ts'] else 300 if not ms['active'] else DISC_TTL):
        _discover(name)


def _candidates(name):
    cfg, ms, now = PROVIDERS[name], _ms[name], time.time()
    env = os.environ.get(cfg['env_model'], '').strip()
    order = ([env] if env else []) + ([ms['active']] if ms['active'] else []) + cfg['defaults'] + ms['discovered']
    seen, out = set(), []
    for m in order:
        if m and m not in seen and ms['bad'].get(m, 0) < now:
            seen.add(m)
            out.append(m)
    return out


def _mark_bad(name, model):
    ms = _ms[name]
    ms['bad'][model] = time.time() + BAD_TTL
    if ms['active'] == model:
        ms['active'] = None


# ── provider calls ───────────────────────────────────────────────────────────
def _attempt(name, model, system, user, max_tokens, temperature, json_mode):
    cfg = PROVIDERS[name]
    if cfg['kind'] == 'gemini':
        gen = {'temperature': temperature,
               'maxOutputTokens': max_tokens + (0 if '2.5' in model else 600)}   # newer models think by default
        if json_mode:
            gen['responseMimeType'] = 'application/json'
        if '2.5' in model and os.environ.get('SOC_GEMINI_NO_THINK', '1') == '1':
            gen['thinkingConfig'] = {'thinkingBudget': 0}
        body = {'systemInstruction': {'parts': [{'text': system}]},
                'contents': [{'role': 'user', 'parts': [{'text': user}]}], 'generationConfig': gen}
        url = f'{GEMINI_BASE}/models/{model}:generateContent'
        hdr = {'x-goog-api-key': _pick_key(name), 'Content-Type': 'application/json'}
        r = requests.post(url, headers=hdr, json=body, timeout=60)
        if r.status_code == 400:                       # unsupported optional settings -> retry lean
            gen.pop('thinkingConfig', None)
            gen.pop('responseMimeType', None)
            r = requests.post(url, headers=hdr, json=body, timeout=60)
        return r
    hdr = {'Authorization': f'Bearer {_pick_key(name)}', 'Content-Type': 'application/json'}
    reasoning = 'gpt-oss' in model
    body = {'model': model, 'max_tokens': max_tokens + (300 if reasoning else 0), 'temperature': temperature,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
    if reasoning and cfg.get('reasoning_effort'):
        body['reasoning_effort'] = 'low'
    if json_mode:
        body['response_format'] = {'type': 'json_object'}
    r = requests.post(cfg['url'], headers=hdr, json=body, timeout=60)
    if r.status_code == 400 and 'tool_use_failed' not in r.text:   # unsupported optional params -> retry lean
        body.pop('response_format', None)
        body.pop('reasoning_effort', None)
        r = requests.post(cfg['url'], headers=hdr, json=body, timeout=60)
    return r


def _parse(name, r):
    data = r.json()
    if PROVIDERS[name]['kind'] == 'gemini':
        parts = (data.get('candidates') or [{}])[0].get('content', {}).get('parts', [])
        text = ''.join(p.get('text', '') for p in parts if not p.get('thought'))
        used = data.get('usageMetadata', {}).get('totalTokenCount', 0)
    else:
        text = (data['choices'][0]['message'].get('content') or '')
        used = data.get('usage', {}).get('total_tokens', 0)
    return text.strip(), used


def _body_hint(r):
    try:
        return r.text[:240].replace('\n', ' ')
    except Exception:
        return ''


def call(task, system, user, tier='fast', max_tokens=350, temperature=0.8, json_mode=True):
    """Returns the reply text, or None if every provider in the chain is unavailable/failed."""
    if _mock:
        return _mock(task, system, user)
    est = (len(system) + len(user)) // 4 + max_tokens + 250
    chain = [n for n in CHAINS.get(tier, CHAINS['fast']) if PROVIDERS[n]['keys']()]
    if not chain:
        log.warning(f'{task}: no LLM provider configured (set GROQ_API_KEY and/or GEMINI_API_KEY)')
        return None
    for attempt in range(2):
        for name in chain:
            with _lock:
                ok = _available(name, est)
                if ok:
                    _reserve(name, est)
            if not ok:
                continue
            st, ms = _state[name], _ms[name]
            _ensure_discovered(name)
            cands = _candidates(name)[:3]
            if not cands:
                st['last_error'] = 'no usable model found'
                st['cooldown'] = time.time() + 600
                log.warning(f'{task}: {name} has no usable model — cooling down 10 min')
                continue
            gone = overloaded = 0
            for model in cands:
                try:
                    r = _attempt(name, model, system, user, max_tokens, temperature, json_mode)
                except requests.exceptions.RequestException as e:
                    st['err'] += 1
                    st['last_error'] = f'{type(e).__name__}: {str(e)[:100]}'
                    st['cooldown'] = time.time() + 20
                    log.warning(f'{task}: {name}/{model} network error — {st["last_error"]}')
                    break
                if r.status_code == 404:
                    gone += 1
                    st['err'] += 1
                    st['last_error'] = f'404 {model}: {_body_hint(r)}'
                    log.warning(f'{task}: {name} model {model} unavailable (404) — {_body_hint(r)}')
                    _mark_bad(name, model)
                    continue
                if r.status_code in (500, 502, 503, 504):   # provider overloaded: try the next model, don't blacklist
                    overloaded += 1
                    st['err'] += 1
                    st['last_error'] = f'{r.status_code} {model}: {_body_hint(r)}'
                    log.warning(f'{task}: {name}/{model} overloaded ({r.status_code}) — trying next model')
                    continue
                if r.status_code == 429:
                    wait = 60
                    try:
                        wait = min(3600, int(float(r.headers.get('retry-after', 60))))
                    except Exception:
                        pass
                    st['cooldown'] = time.time() + wait
                    st['err'] += 1
                    st['last_error'] = f'429 on {model} (cooldown {wait}s)'
                    log.warning(f'{task}: {name}/{model} rate-limited, cooling down {wait}s')
                    break
                if r.status_code == 400 and 'tool_use_failed' in r.text:
                    # gpt-oss sometimes answers in function-call form; Groq rejects it but returns the text
                    fg = ''
                    try:
                        fg = (r.json().get('error') or {}).get('failed_generation') or ''
                    except Exception:
                        pass
                    if fg and extract_json(fg):
                        st['ok'] += 1
                        ms['active'] = model
                        return fg
                if r.status_code >= 400:
                    st['err'] += 1
                    st['last_error'] = f'{r.status_code} {model}: {_body_hint(r)}'
                    log.warning(f'{task}: {name}/{model} HTTP {r.status_code} — {_body_hint(r)}')
                    break
                try:
                    text, used = _parse(name, r)
                except Exception as e:
                    st['err'] += 1
                    st['last_error'] = f'unreadable reply from {model}: {type(e).__name__}'
                    break
                with _lock:
                    _settle(name, est, used)
                if text:
                    st['ok'] += 1
                    ms['active'] = model
                    return text
                st['last_error'] = f'empty reply from {model}'
                log.warning(f'{task}: {name}/{model} returned an empty reply')
                break
            if overloaded and overloaded == len(cands):
                st['cooldown'] = time.time() + 60
            if gone and gone == len(cands):             # every candidate was 404 — rediscover soon, back off
                ms['discovered'] = []
                ms['disc_ts'] = 0.0
                st['cooldown'] = time.time() + 900
        with _lock:
            recoverable = any(_daily_ok(n, est) for n in chain)
        if attempt == 0 and recoverable:
            time.sleep(12)   # per-minute window / cooldown — wait once, then retry
        else:
            break
    return None


# ── observability ────────────────────────────────────────────────────────────
def status():
    out = {}
    with _lock:
        for n, cfg in PROVIDERS.items():
            st = _state[n]
            _reset_day(st)
            cands = _candidates(n)
            out[n] = dict(configured=bool(cfg['keys']()), model=(_ms[n]['active'] or (cands[0] if cands else 'auto')),
                          tokens_today=st['day_tokens'], token_cap=cfg['tpd'],
                          requests_today=st['day_reqs'], request_cap=cfg['rpd'],
                          ok=st['ok'], errors=st['err'], last_error=st['last_error'],
                          cooling=max(0, int(st['cooldown'] - time.time())))
    return out


def diagnose():
    """Live probe of every configured provider (used by /api/society/admin/diag). Not budget-counted."""
    report = {}
    for name, cfg in PROVIDERS.items():
        if not cfg['keys']():
            report[name] = {'configured': False}
            continue
        ms = _ms[name]
        ms['bad'] = {}                                   # forget old failures so the probe is honest
        _discover(name)
        row = {'configured': True, 'discovered': ms['discovered'], 'tried': []}
        for model in _candidates(name)[:5]:
            try:
                r = _attempt(name, model, 'You are a test.', 'Reply with the single word OK.', 20, 0.0, False)
                entry = {'model': model, 'status': r.status_code}
                if r.status_code < 400:
                    text, _ = _parse(name, r)
                    entry['reply'] = text[:40]
                    row['tried'].append(entry)
                    row['working_model'] = model
                    ms['active'] = model
                    break
                entry['error'] = _body_hint(r)
                if r.status_code == 404:
                    _mark_bad(name, model)
            except Exception as e:
                entry = {'model': model, 'error': f'{type(e).__name__}: {str(e)[:120]}'}
            row['tried'].append(entry)
        row.setdefault('working_model', None)
        report[name] = row
    return report


def export_budget():
    with _lock:
        return {'day': _today(), 'p': {n: [s['day_tokens'], s['day_reqs']] for n, s in _state.items()}}


def import_budget(d):
    if not isinstance(d, dict) or d.get('day') != _today():
        return
    with _lock:
        for n, (tok, req) in (d.get('p') or {}).items():
            if n in _state:
                _reset_day(_state[n])
                _state[n]['day_tokens'] = max(_state[n]['day_tokens'], int(tok))
                _state[n]['day_reqs'] = max(_state[n]['day_reqs'], int(req))
