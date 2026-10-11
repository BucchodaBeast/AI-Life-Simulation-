"""
society/world.py — the clock, the seasons, selection and birth.

tick():   every SOC_TICK_MINUTES. A few citizens (weighted by energy) each take one turn.
season(): every SOC_SEASON_HOURS. Fitness is scored; if a bonded pair is mature enough
          they can have a child (crossover + mutation). At the population cap the
          weakest mature citizen is retired to the archive to make room.

Fitness (0-100) = 60% peer-review quality + 15% productivity + 25% social standing,
nudged by public reactions (agree / flag) on their work.
"""
import re, json, random, logging, threading
from datetime import datetime, timezone

from . import config, llm, agent as agent_mod, social
from .store import get_store, now_iso
from .founders import FOUNDERS, founder_genome, NAME_POOL
from .genome import crossover, top_interests
from .voices import voice_color, voice_keys

log = logging.getLogger('society.world')
TICK_LOCK = threading.Lock()


def _slug(name):
    return re.sub(r'[^a-z0-9]+', '', name.lower())


def get_alive(store):
    return store.select('soc_agents', {'status': 'alive'}, order='born_tick')


def ensure_seeded(store):
    if store.select('soc_agents', limit=1):
        return False
    for f in FOUNDERS:
        store.insert('soc_agents', dict(
            id=_slug(f['name']), name=f['name'], status='alive', generation=1, parents=[], voice=f['voice'],
            backstory=f['backstory'], genome=founder_genome(f), energy=80.0, profession='', domain_xp={},
            born_tick=0, born_at=now_iso(), retired_at='', fitness=0.0, color=voice_color(f['voice'])))
    store.world_set('tick', 0)
    store.world_set('last_season', now_iso())
    store.event(0, '', 'genesis', f'{len(FOUNDERS)} founding citizens wake up in the Signal Society.', {})
    log.info('Society seeded with founders')
    return True


def _choose_actors(alive):
    pool = [a for a in alive if a['energy'] >= 8]
    n = min(config.AGENTS_PER_TICK, len(pool))
    chosen = []
    for _ in range(n):
        weights = [max(1.0, a['energy']) for a in pool]
        pick = random.choices(pool, weights=weights, k=1)[0]
        chosen.append(pick)
        pool.remove(pick)
    return chosen


def tick():
    """One turn of the world. Safe to call from the scheduler or an admin endpoint."""
    if not TICK_LOCK.acquire(blocking=False):
        return {'ok': False, 'reason': 'busy'}
    try:
        store = get_store()
        ensure_seeded(store)
        try:
            llm.import_budget(json.loads(store.world_get('budget', '{}') or '{}'))
        except Exception:
            pass
        t = int(store.world_get('tick', '0') or 0) + 1
        store.world_set('tick', t)
        alive = get_alive(store)
        for a in alive:                                   # passive energy regen
            if a['energy'] < 100:
                a['energy'] = min(100.0, a['energy'] + config.PASSIVE_REGEN)
                store.update('soc_agents', {'id': a['id']}, {'energy': a['energy']})
        report = []
        for a in _choose_actors(alive):
            try:
                ctx = agent_mod.build_context(store, a, alive, t)
                d, _ = agent_mod.decide(a, ctx, len(alive))
                if d is None:
                    report.append((a['name'], 'no-decision'))
                    continue
                report.append((a['name'], agent_mod.act(store, a, d, ctx, alive, t)))
            except Exception as e:
                log.exception(f"turn failed for {a['name']}: {e}")
                report.append((a['name'], f'error:{type(e).__name__}'))
        store.world_set('last_tick_at', now_iso())
        store.world_set('last_report', json.dumps(report))
        season_result = season(store, t)
        store.world_set('budget', json.dumps(llm.export_budget()))
        return {'ok': True, 'tick': t, 'report': report, 'season': bool(season_result)}
    except Exception as e:
        log.exception(f'tick failed: {e}')
        return {'ok': False, 'reason': f'{type(e).__name__}: {e}'}
    finally:
        TICK_LOCK.release()


def tick_safe():
    try:
        tick()
    except Exception as e:                                # the scheduler must never die
        log.exception(f'society tick crashed: {e}')


# ── fitness & selection ──────────────────────────────────────────────────────
def compute_fitness(store, a):
    fs = store.select('soc_findings', {'agent': a['id']}, order='-ts', limit=60)
    reviewed = [f for f in fs if f['review_count'] >= config.REVIEWS_NEEDED]
    quality = (sum(f['review_avg'] for f in reviewed[:12]) / len(reviewed[:12]) * 10) if reviewed else 0.0
    productivity = min(1.0, len(fs) / 10) * 100
    pos = sum(max(0.0, r['affinity']) for r in social.rels_for(store, a['id']))
    standing = min(100.0, pos * 8)
    react = sum((f['reactions'] or {}).get('agree', 0) - (f['reactions'] or {}).get('flag', 0) for f in fs)
    return round(max(0.0, min(100.0, 0.6 * quality + 0.15 * productivity + 0.25 * standing
                              + max(-10, min(10, 2 * react)))), 1)


def season(store, tick, force=False):
    last = store.world_get('last_season', '')
    if not force and last:
        try:
            hrs = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
            if hrs < config.SEASON_HOURS:
                return None
        except Exception:
            pass
    alive = get_alive(store)
    for a in alive:
        a['fitness'] = compute_fitness(store, a)
        store.update('soc_agents', {'id': a['id']}, {'fitness': a['fitness']})
        mem = store.select('soc_memories', {'agent': a['id']}, order='-ts')
        for old in mem[40:]:
            store.delete('soc_memories', {'id': old['id']})
    store.world_set('last_season', now_iso())
    child = reproduce(store, tick, alive)
    top = max(alive, key=lambda x: x['fitness']) if alive else None
    store.event(tick, '', 'season',
                'A season ends. ' + (f"Fittest citizen: {top['name']} ({top['fitness']:.0f})." if top else '')
                + (f" A child was born: {child['name']}." if child else ' No child this season.'), {})
    return {'child': child['name'] if child else None}


def _pick_name(store):
    taken = {a['name'].lower() for a in store.select('soc_agents')}
    for n in NAME_POOL:
        if n.lower() not in taken:
            return n
    return f'Gen{random.randint(100, 999)}'


def reproduce(store, tick, alive):
    by_id = {a['id']: a for a in alive}
    mature = [a for a in alive if tick - a['born_tick'] >= config.MIN_AGE_TICKS]
    best, best_score = None, -1e9
    seen = set()
    for a in mature:
        for r in social.rels_for(store, a['id']):
            if r['pair'] in seen:
                continue
            seen.add(r['pair'])
            x, y = by_id.get(r['a']), by_id.get(r['b'])
            if not x or not y or x not in mature or y not in mature:
                continue
            if r['kind'] == 'partner' or (r['kind'] == 'friend' and r['affinity'] >= 6):
                score = r['affinity'] + (x['fitness'] + y['fitness']) / 50
                if score > best_score:
                    best, best_score = (x, y), score
    if not best:
        return None
    pa, pb = best
    if len(alive) >= config.POP_CAP:
        season_ticks = max(config.MIN_AGE_TICKS, config.SEASON_HOURS * 60 // max(1, config.TICK_MINUTES))
        # a citizen must have lived a full season before selection can retire it (newborns get a fair run)
        victims = [a for a in mature if a['id'] not in (pa['id'], pb['id'])
                   and tick - a['born_tick'] >= season_ticks]
        if not victims:
            return None
        weakest = min(victims, key=lambda a: a['fitness'])
        if weakest['fitness'] >= (pa['fitness'] + pb['fitness']) / 2:
            return None                                    # no selection pressure without a weaker citizen
        store.update('soc_agents', {'id': weakest['id']}, {'status': 'retired', 'retired_at': now_iso()})
        store.event(tick, weakest['id'], 'retire',
                    f"{weakest['name']} (generation {weakest['generation']}, fitness {weakest['fitness']:.0f}) "
                    f"passes into the archive to make room for the next generation.", {})
    ka, kb = voice_keys(pa['voice']), voice_keys(pb['voice'])
    voice = random.choice([pa['voice'], pb['voice']])
    if random.random() < 0.3 and ka[0] != kb[0]:
        voice = f'{ka[0]}+{kb[0]}'                         # hybrid accent
    name = _pick_name(store)
    gen = max(pa['generation'], pb['generation']) + 1
    child = dict(
        id=_slug(name), name=name, status='alive', generation=gen, parents=[pa['id'], pb['id']], voice=voice,
        backstory=f"Born in generation {gen} to {pa['name']} and {pb['name']}; carries a little of each of them.",
        genome=crossover(pa['genome'], pb['genome']), energy=70.0, profession='', domain_xp={},
        born_tick=tick, born_at=now_iso(), retired_at='', fitness=0.0, color=voice_color(voice))
    store.insert('soc_agents', child)
    for p in (pa, pb):
        social.set_kind(store, child['id'], p['id'], 'family', extra_affinity=5.0)
        store.remember(p['id'], f"{name} was born to {pa['name']} and {pb['name']}.", importance=3)
    store.remember(child['id'], f"I was born to {pa['name']} and {pb['name']}.", importance=3)
    store.event(tick, child['id'], 'birth',
                f"{name} is born to {pa['name']} and {pb['name']} (generation {gen}). "
                f"Interests: {', '.join(top_interests(child['genome']))}.",
                {'parents': [pa['name'], pb['name']], 'generation': gen})
    return child


# ── read models for the API ──────────────────────────────────────────────────
def snapshot(store):
    agents = store.select('soc_agents', order='born_tick')
    tick = int(store.world_get('tick', '0') or 0)
    rels = [r for r in store.select('soc_relationships') if r['kind'] != 'stranger' or r['interactions'] > 0]
    return dict(
        enabled=config.enabled(), backend=store.backend, fallback_reason=store.fallback_reason, tick=tick,
        last_tick_at=store.world_get('last_tick_at', ''), last_season=store.world_get('last_season', ''),
        agents=agents, relationships=rels, llm=llm.status(),
        config=dict(tick_minutes=config.TICK_MINUTES, agents_per_tick=config.AGENTS_PER_TICK,
                    pop_cap=config.POP_CAP, season_hours=config.SEASON_HOURS))
