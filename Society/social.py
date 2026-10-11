"""
society/social.py — relationships between citizens.

One row per unordered pair. affinity is -10..10. `kind` moves through:
  stranger -> acquaintance -> friend -> partner      (friend/partner need an accepted bond)
  any -> rival when affinity drops to -4 or below
"""
from .config import MAX_AFFINITY
from .store import now_iso


def pair_key(a, b):
    return '|'.join(sorted([a, b]))


def get_rel(store, a, b):
    rows = store.select('soc_relationships', {'pair': pair_key(a, b)}, limit=1)
    return rows[0] if rows else None


def rels_for(store, agent_id):
    return (store.select('soc_relationships', {'a': agent_id}) +
            store.select('soc_relationships', {'b': agent_id}))


def _normalize(rel):
    """Returns (new_kind, old_kind) after applying threshold rules."""
    old = new = rel['kind']
    aff, n = rel['affinity'], rel['interactions']
    if new == 'partner' and aff < 2:
        new = 'friend'
    if new == 'friend' and aff < 0:
        new = 'acquaintance'
    if new in ('stranger', 'acquaintance') and aff <= -4:
        new = 'rival'
    if new == 'rival' and aff > -2:
        new = 'acquaintance'
    if new == 'stranger' and n >= 2:
        new = 'acquaintance'
    return new, old


def bump(store, a, b, delta=0.0, interact=True):
    """Adjust affinity between a and b. Returns (rel, old_kind) so callers can log changes."""
    rel = get_rel(store, a, b)
    if rel is None:
        x, y = sorted([a, b])
        rel = store.insert('soc_relationships', dict(pair=pair_key(a, b), a=x, b=y, affinity=0.0,
                                                     kind='stranger', interactions=0, updated_at=now_iso()))
    rel['affinity'] = max(-MAX_AFFINITY, min(MAX_AFFINITY, rel['affinity'] + delta))
    if interact:
        rel['interactions'] += 1
    new, old = _normalize(rel)
    rel['kind'] = new
    store.update('soc_relationships', {'id': rel['id']},
                 dict(affinity=round(rel['affinity'], 2), kind=new,
                      interactions=rel['interactions'], updated_at=now_iso()))
    return rel, old


def set_kind(store, a, b, kind, extra_affinity=0.0):
    rel, _ = bump(store, a, b, extra_affinity, interact=True)
    store.update('soc_relationships', {'id': rel['id']}, dict(kind=kind, updated_at=now_iso()))
    rel['kind'] = kind
    return rel


def partner_of(store, agent_id, alive_ids=None):
    for r in rels_for(store, agent_id):
        if r['kind'] == 'partner':
            other = r['b'] if r['a'] == agent_id else r['a']
            if alive_ids is None or other in alive_ids:
                return other
    return None
