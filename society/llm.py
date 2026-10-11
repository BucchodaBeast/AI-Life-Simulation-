"""
society/llm.py — multi-model gateway for the Society (all free tiers).

Tiers
  fast  — routine decisions, reviews, chat.      Groq llama-3.1-8b-instant first.
  smart — writing findings and innovations.      Gemini 2.5 Flash first.

Why not the 70B? Your live app already spends the 70B's ~100k tokens/day.
The 8B has its own 500k/day pool, and Gemini has its own project quota, so the
Society never competes with the live agents. (You can opt the 70B in with
SOC_USE_GROQ_70B=1; it gets a small daily slice so it can't starve the live app.)

Each provider has its own per-minute / per-day accounting. If one is full or
returns 429 the next one in the chain is tried. Providers without a key are skipped.
"""
import os, re, json, time, threading, logging
from collections import deque
from datetime import datetime, timezone
import requests

from . import config

log = logging.getLogger('society.llm')
_lock = threading.Lock()
_mock = None   # tests can install a fake: fn(task, system, user) -> str


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


# Limits are deliberately conservative (free tiers change — check your consoles).
PROVIDERS = {
    'groq_fast': dict(kind='openai', url='https://api.groq.com/openai/v1/chat/completions',
                      keys=_groq_keys, model=config.FAST_MODEL,
                      rpm=_int('SOC_GROQ_RPM', 20), tpm=_int('SOC_GROQ_TPM', 5500),
                      tpd=_int('SOC_GROQ_FAST_TPD', 400000), rpd=_int('SOC_GROQ_FAST_RPD', 12000)),
    'groq_70b': dict(kind='openai', url='https://api.groq.com/openai/v1/chat/completions',
                     keys=lambda: _groq_keys() if os.environ.get('SOC_USE_GROQ_70B', '0') == '1' else [],
                     model=config.GROQ_70B,
                     rpm=10, tpm=9000, tpd=_int('SOC_GROQ_70B_TPD', 25000), rpd=200),
    'gemini': dict(kind='gemini', keys=_env_key('GEMINI_API_KEY'), model=config.GEMINI_MODEL,
                   rpm=_int('SOC_GEMINI_RPM', 8), tpm=_int('SOC_GEMINI_TPM', 200000),
                   tpd=_int('SOC_GEMINI_TPD', 600000), rpd=_int('SOC_GEMINI_RPD', 180)),
    'openrouter': dict(kind='openai', url='https://openrouter.ai/api/v1/chat/completions',
                       keys=_env_key('OPENROUTER_API_KEY'), model=config.OPENROUTER_MODEL,
                       rpm=_int('SOC_OPENROUTER_RPM', 12), tpm=60000,
                       tpd=_int('SOC_OPENROUTER_TPD', 200000), rpd=_int('SOC_OPENROUTER_RPD', 120)),
}

CHAINS = {
    'fast':  ['groq_fast', 'openrouter', 'gemini'],
    'smart': ['groq_70b', 'gemini', 'groq_fast', 'openrouter'],
}

_state = {n: dict(req=deque(), tok=deque(), day='', day_tokens=0, day_reqs=0,
                  cooldown=0.0, ok=0, err=0, last_error='') for n in PROVIDERS}
_key_idx = {'groq': 0}


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
    st = _state[name]
    st['day_tokens'] += max(0, actual - est)


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


def _pick_key(name):
    keys = PROVIDERS[name]['keys']()
    if not keys:
        return ''
    if name.startswith('groq'):
        _key_idx['groq'] = (_key_idx['groq'] + 1) % len(keys)
        return keys[_key_idx['groq']]
    return keys[0]


def _call_openai(name, system, user, max_tokens, temperature, json_mode):
    cfg = PROVIDERS[name]
    headers = {'Authorization': f'Bearer {_pick_key(name)}', 'Content-Type': 'application/json'}
    body = {'model': cfg['model'], 'max_tokens': max_tokens, 'temperature': temperature,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
    if json_mode:
        body['response_format'] = {'type': 'json_object'}
    r = requests.post(cfg['url'], headers=headers, json=body, timeout=45)
    if r.status_code == 400 and json_mode:      # some free models reject json mode
        body.pop('response_format', None)
        r = requests.post(cfg['url'], headers=headers, json=body, timeout=45)
    return r


def _call_gemini(name, system, user, max_tokens, temperature, json_mode):
    cfg = PROVIDERS[name]
    gen = {'temperature': temperature, 'maxOutputTokens': max_tokens}
    if json_mode:
        gen['responseMimeType'] = 'application/json'
    if os.environ.get('SOC_GEMINI_NO_THINK', '1') == '1':
        gen['thinkingConfig'] = {'thinkingBudget': 0}
    body = {'systemInstruction': {'parts': [{'text': system}]},
            'contents': [{'role': 'user', 'parts': [{'text': user}]}],
            'generationConfig': gen}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent"
    r = requests.post(url, headers={'x-goog-api-key': _pick_key(name), 'Content-Type': 'application/json'},
                      json=body, timeout=60)
    if r.status_code == 400 and 'thinking' in r.text.lower():   # model without thinking control
        gen.pop('thinkingConfig', None)
        r = requests.post(url, headers={'x-goog-api-key': _pick_key(name), 'Content-Type': 'application/json'},
                          json=body, timeout=60)
    return r


def _parse(name, r):
    data = r.json()
    if PROVIDERS[name]['kind'] == 'gemini':
        parts = data['candidates'][0]['content']['parts']
        text = ''.join(p.get('text', '') for p in parts)
        used = data.get('usageMetadata', {}).get('totalTokenCount', 0)
    else:
        text = data['choices'][0]['message']['content']
        used = data.get('usage', {}).get('total_tokens', 0)
    return (text or '').strip(), used


def call(task, system, user, tier='fast', max_tokens=350, temperature=0.8, json_mode=True):
    """Returns the reply text, or None if every provider in the chain is unavailable/failed."""
    if _mock:
        return _mock(task, system, user)
    est = (len(system) + len(user)) // 4 + max_tokens
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
            st = _state[name]
            try:
                fn = _call_gemini if PROVIDERS[name]['kind'] == 'gemini' else _call_openai
                r = fn(name, system, user, max_tokens, temperature, json_mode)
                if r.status_code == 429:
                    wait = 60
                    try:
                        wait = min(300, int(float(r.headers.get('retry-after', 60))))
                    except Exception:
                        pass
                    st['cooldown'] = time.time() + wait
                    st['err'] += 1
                    st['last_error'] = f'429 (cooldown {wait}s)'
                    log.warning(f'{task}: {name} rate-limited, cooling down {wait}s')
                    continue
                r.raise_for_status()
                text, used = _parse(name, r)
                with _lock:
                    _settle(name, est, used)
                st['ok'] += 1
                if text:
                    return text
            except Exception as e:
                st['err'] += 1
                st['last_error'] = f'{type(e).__name__}: {str(e)[:120]}'
                log.warning(f'{task}: {name} failed — {st["last_error"]}')
                if isinstance(e, requests.exceptions.RequestException):
                    st['cooldown'] = time.time() + 20
        with _lock:
            recoverable = any(_daily_ok(n, est) for n in chain)
        if attempt == 0 and recoverable:
            time.sleep(12)   # per-minute window / cooldown — wait once, then retry
        else:
            break
    return None


def status():
    out = {}
    with _lock:
        for n, cfg in PROVIDERS.items():
            st = _state[n]
            _reset_day(st)
            out[n] = dict(configured=bool(cfg['keys']()), model=cfg['model'],
                          tokens_today=st['day_tokens'], token_cap=cfg['tpd'],
                          requests_today=st['day_reqs'], request_cap=cfg['rpd'],
                          ok=st['ok'], errors=st['err'], last_error=st['last_error'],
                          cooling=max(0, int(st['cooldown'] - time.time())))
    return out


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
