"""
society/api.py — read-only public API + the /society page, plus token-guarded admin triggers.
"""
import hmac, threading, logging
from flask import Blueprint, jsonify, request, send_from_directory, current_app

from . import config, world
from .store import get_store
from .voices import voice_label, voice_color

log = logging.getLogger('society.api')
bp = Blueprint('society', __name__)
_reacted = set()          # (ip, finding_id, reaction) — per-process dedup, good enough for a demo


def _store():
    return get_store()


def _decorate_agent(a):
    a = dict(a)
    a['voice_label'] = voice_label(a['voice'])
    a['color'] = voice_color(a['voice'])
    return a


@bp.route('/society')
def society_page():
    return send_from_directory(current_app.root_path, 'society.html')


@bp.route('/api/society/state')
def state():
    try:
        snap = world.snapshot(_store())
        snap['agents'] = [_decorate_agent(a) for a in snap['agents']]
        return jsonify(snap)
    except Exception as e:
        log.exception('state failed')
        return jsonify(error=f'{type(e).__name__}: {e}', enabled=config.enabled(), agents=[], relationships=[]), 500


@bp.route('/api/society/events')
def events():
    store = _store()
    limit = max(1, min(int(request.args.get('limit', 60)), 200))
    where = {}
    if request.args.get('before'):
        where['ts'] = ('<', request.args['before'])
    if request.args.get('type'):
        where['type'] = request.args['type']
    rows = store.select('soc_events', where or None, order='-ts', limit=limit)
    agents = {a['id']: a for a in store.select('soc_agents')}
    for r in rows:
        a = agents.get(r['agent'])
        r['name'] = a['name'] if a else ''
        r['color'] = voice_color(a['voice']) if a else '#888888'
    return jsonify(events=rows)


@bp.route('/api/society/findings')
def findings():
    store = _store()
    limit = max(1, min(int(request.args.get('limit', 40)), 100))
    where = {}
    if request.args.get('kind'):
        where['kind'] = request.args['kind']
    if request.args.get('agent'):
        where['agent'] = request.args['agent']
    rows = store.select('soc_findings', where or None, order='-ts', limit=limit)
    agents = {a['id']: a for a in store.select('soc_agents')}
    for r in rows:
        a = agents.get(r['agent'])
        r['name'] = a['name'] if a else ''
        r['color'] = voice_color(a['voice']) if a else '#888888'
    return jsonify(findings=rows)


@bp.route('/api/society/agents/<agent_id>')
def agent_detail(agent_id):
    store = _store()
    a = store.get('soc_agents', agent_id)
    if not a:
        return jsonify(error='not found'), 404
    agents = {x['id']: x for x in store.select('soc_agents')}
    from . import social
    rels = []
    for r in social.rels_for(store, agent_id):
        oid = r['b'] if r['a'] == agent_id else r['a']
        if oid in agents:
            rels.append(dict(with_=agents[oid]['name'], kind=r['kind'], affinity=r['affinity'],
                             interactions=r['interactions']))
    mems = store.select('soc_memories', {'agent': agent_id}, order='-ts', limit=12)
    works = store.select('soc_findings', {'agent': agent_id}, order='-ts', limit=10)
    return jsonify(agent=_decorate_agent(a), relationships=rels,
                   memories=[m['text'] for m in mems],
                   works=[dict(id=w['id'], kind=w['kind'], title=w['title'], domain=w['domain'],
                               review_avg=w['review_avg'], review_count=w['review_count']) for w in works],
                   parents=[agents[p]['name'] for p in a['parents'] if p in agents])


@bp.route('/api/society/react', methods=['POST'])
def react():
    body = request.get_json(silent=True) or {}
    fid, reaction = body.get('finding_id', ''), body.get('reaction', '')
    if reaction not in ('agree', 'flag'):
        return jsonify(error='reaction must be agree or flag'), 400
    key = (request.headers.get('X-Forwarded-For', request.remote_addr), fid, reaction)
    if key in _reacted:
        return jsonify(error='already reacted'), 409
    store = _store()
    f = store.get('soc_findings', fid)
    if not f:
        return jsonify(error='not found'), 404
    r = f['reactions'] or {}
    r[reaction] = r.get(reaction, 0) + 1
    store.update('soc_findings', {'id': fid}, {'reactions': r})
    _reacted.add(key)
    return jsonify(reactions=r)


# ── admin (disabled unless SOC_ADMIN_TOKEN is set) ───────────────────────────
def _authorised():
    token = config.admin_token()
    given = request.headers.get('X-Admin-Token', '')
    return bool(token) and hmac.compare_digest(token, given)


@bp.route('/api/society/admin/tick', methods=['POST'])
def admin_tick():
    if not _authorised():
        return jsonify(error='forbidden'), 403
    if request.args.get('wait') == '1':
        return jsonify(world.tick())
    threading.Thread(target=world.tick_safe, daemon=True).start()
    return jsonify(started=True)


@bp.route('/api/society/admin/season', methods=['POST'])
def admin_season():
    if not _authorised():
        return jsonify(error='forbidden'), 403
    store = _store()
    world.ensure_seeded(store)
    tick = int(store.world_get('tick', '0') or 0)
    return jsonify(result=world.season(store, tick, force=True))
