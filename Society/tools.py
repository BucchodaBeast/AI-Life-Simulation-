"""
society/tools.py — the real web, as citizens can reach it.

Every tool is free and key-less, takes a short text query and returns a list of
{title, snippet, url, source}. Fixed endpoints only (no user-supplied URLs), short
timeouts, tiny payloads — safe for Render's 512MB free tier.
"""
import re, logging
from urllib.parse import quote
import requests
import feedparser

log = logging.getLogger('society.tools')
HEADERS = {'User-Agent': 'SignalSociety/2.0 (research demo)'}
TIMEOUT = 12
MAX_ITEMS = 4


def _get(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def _clean(s, n=240):
    s = re.sub(r'<[^>]+>', '', s or '')
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:n]


def arxiv(q):
    r = _get('http://export.arxiv.org/api/query',
             {'search_query': f'all:{q}', 'max_results': MAX_ITEMS, 'sortBy': 'relevance'})
    out = []
    for e in feedparser.parse(r.text).entries[:MAX_ITEMS]:
        out.append(dict(title=_clean(e.get('title'), 140), snippet=_clean(e.get('summary'), 260),
                        url=e.get('link', ''), source='arXiv'))
    return out


def openalex(q):
    r = _get('https://api.openalex.org/works',
             {'search': q, 'per-page': MAX_ITEMS,
              'select': 'id,title,publication_year,cited_by_count,doi,abstract_inverted_index'})
    out = []
    for w in r.json().get('results', [])[:MAX_ITEMS]:
        inv = w.get('abstract_inverted_index') or {}
        words = sorted(((p, word) for word, pos in inv.items() for p in pos))
        abstract = ' '.join(word for _, word in words[:45])
        meta = f"{w.get('publication_year')}, cited {w.get('cited_by_count', 0)} times"
        out.append(dict(title=_clean(w.get('title'), 140), snippet=_clean(f'{meta}. {abstract}', 260),
                        url=w.get('doi') or w.get('id') or '', source='OpenAlex'))
    return out


def wikipedia(q):
    r = _get('https://en.wikipedia.org/w/api.php',
             {'action': 'query', 'list': 'search', 'srsearch': q, 'srlimit': MAX_ITEMS,
              'format': 'json', 'srprop': 'snippet'})
    out = []
    for h in r.json().get('query', {}).get('search', [])[:MAX_ITEMS]:
        out.append(dict(title=h.get('title', ''), snippet=_clean(h.get('snippet'), 260),
                        url=f"https://en.wikipedia.org/?curid={h.get('pageid')}", source='Wikipedia'))
    return out


def hackernews(q):
    r = _get('https://hn.algolia.com/api/v1/search',
             {'query': q, 'tags': 'story', 'hitsPerPage': MAX_ITEMS})
    out = []
    for h in r.json().get('hits', [])[:MAX_ITEMS]:
        out.append(dict(title=_clean(h.get('title'), 140),
                        snippet=f"{h.get('points', 0)} points, {h.get('num_comments', 0)} comments on Hacker News",
                        url=h.get('url') or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                        source='Hacker News'))
    return out


def news(q):
    r = _get(f'https://news.google.com/rss/search?q={quote(q)}&hl=en-US&gl=US&ceid=US:en')
    out = []
    for e in feedparser.parse(r.text).entries[:MAX_ITEMS]:
        out.append(dict(title=_clean(e.get('title'), 160), snippet=f"Published {e.get('published', 'recently')}",
                        url=e.get('link', ''), source='Google News'))
    return out


WB_INDICATORS = {
    'population': 'SP.POP.TOTL', 'gdp per capita': 'NY.GDP.PCAP.CD', 'gdp': 'NY.GDP.MKTP.CD',
    'unemployment': 'SL.UEM.TOTL.ZS', 'electricity': 'EG.ELC.ACCS.ZS', 'life expectancy': 'SP.DYN.LE00.IN',
    'child mortality': 'SH.DYN.MORT', 'infant': 'SP.DYN.IMRT.IN', 'poverty': 'SI.POV.DDAY',
    'internet': 'IT.NET.USER.ZS', 'inflation': 'FP.CPI.TOTL.ZG', 'agriculture': 'NV.AGR.TOTL.ZS',
    'arable': 'AG.LND.ARBL.ZS', 'school': 'SE.PRM.ENRR', 'literacy': 'SE.ADT.LITR.ZS',
    'health expenditure': 'SH.XPD.CHEX.GD.ZS', 'renewable': 'EG.FEC.RNEW.ZS', 'co2': 'EN.ATM.CO2E.PC',
    'forest': 'AG.LND.FRST.ZS', 'hiv': 'SH.DYN.AIDS.ZS',
}
WB_COUNTRIES = {'eswatini': 'SWZ', 'swaziland': 'SWZ', 'south africa': 'ZAF', 'kenya': 'KEN',
                'nigeria': 'NGA', 'mozambique': 'MOZ', 'zimbabwe': 'ZWE', 'world': 'WLD', 'global': 'WLD'}


def worldbank(q):
    ql = q.lower()
    ind = next((code for kw, code in sorted(WB_INDICATORS.items(), key=lambda kv: -len(kv[0])) if kw in ql), None)
    if not ind:
        return []
    country = next((c for k, c in WB_COUNTRIES.items() if k in ql), 'SWZ')
    r = _get(f'https://api.worldbank.org/v2/country/{country}/indicator/{ind}',
             {'format': 'json', 'per_page': 8})
    data = r.json()
    rows = [x for x in (data[1] if len(data) > 1 and data[1] else []) if x.get('value') is not None][:6]
    if not rows:
        return []
    name = rows[0]['indicator']['value']
    series = '; '.join(f"{x['date']}: {round(x['value'], 2)}" for x in rows)
    return [dict(title=f"{name} — {rows[0]['country']['value']}", snippet=series,
                 url=f'https://data.worldbank.org/indicator/{ind}?locations={country[:2]}', source='World Bank')]


TOOLS = {
    'arxiv':      (arxiv,      'research preprints (science, tech, health, economics)'),
    'openalex':   (openalex,   'peer-reviewed literature with citation counts'),
    'wikipedia':  (wikipedia,  'background knowledge and definitions'),
    'hackernews': (hackernews, 'tech community stories and discussion'),
    'news':       (news,       'current news headlines worldwide'),
    'worldbank':  (worldbank,  "country statistics. Query like 'unemployment eswatini', 'electricity south africa'"),
}


def describe_tools() -> str:
    return '\n'.join(f'- {n}: {d}' for n, (_, d) in TOOLS.items())


def run_tool(name: str, query: str) -> list:
    """Never raises. Returns [] on any failure."""
    entry = TOOLS.get((name or '').lower().strip())
    q = re.sub(r'\s+', ' ', (query or '')).strip()[:90]
    if not entry or len(q) < 3:
        return []
    try:
        return [x for x in entry[0](q) if x.get('title')][:MAX_ITEMS]
    except Exception as e:
        log.warning(f'tool {name} failed for "{q}": {type(e).__name__}: {str(e)[:100]}')
        return []
