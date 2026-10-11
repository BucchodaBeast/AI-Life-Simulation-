"""Offline simulation: fake LLM + fake tools. Verifies the mechanics end-to-end."""
import os, re, json, random, tempfile, logging, sys
os.environ['SOC_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'soc.db')
os.environ['SOC_FORCE_SQLITE'] = '1'
os.environ['SOC_ENABLED'] = '1'
os.environ['SOC_AGENTS_PER_TICK'] = '3'
os.environ['SOC_MIN_AGE_TICKS'] = '15'
os.environ['SOC_SEASON_HOURS'] = '10'
logging.basicConfig(level=logging.WARNING)
random.seed(7)

from society import llm, tools, world, config, social
from society.store import get_store

DOMS = config.DOMAINS
def fake_tool(name, q):
    return [dict(title=f'{q} study {i}', snippet=f'Result about {q} number {i}, 12% change in 2024.', url=f'https://x.org/{i}', source=name) for i in range(1, 4)]
tools.run_tool = lambda n, q: fake_tool(n, q) if n in tools.TOOLS else []
import society.agent as ag
ag.tools.run_tool = tools.run_tool

def mock(task, system, user):
    if task == 'decide':
        names = re.search(r'CITIZENS: (.*)', user).group(1)
        names = [re.sub(r' \(.*?\)', '', n).strip() for n in re.split(r'\), ', names + ')')] 
        names = [n.rstrip(')').strip() for n in re.findall(r'([A-Z][a-z]+) \(', 'CITIZENS: ' + re.search(r'CITIZENS: (.*)', user).group(1))]
        acts = re.search(r'"action": "<([^>]*)>', user).group(1).split('|')
        weights = {'search': 5, 'message': 5, 'respond': 20, 'review': 8, 'innovate': 10, 'gene_swap': 3, 'rest': 1}
        act = random.choices(acts, [weights[a] for a in acts])[0]
        to = random.choice(names)
        d = {'thought': 'mock thought', 'action': act}
        if act == 'search':
            d.update(tool=random.choice(list(tools.TOOLS)), query='drought maize yields', domain=random.choice(DOMS))
        if act == 'message':
            d.update(to=to, body=f'Hey {to}, what do you make of this?', bond=random.choice([None, 'friendship', 'romance', 'friendship']))
        if act == 'respond':
            m = re.search(r'PROPOSALS TO YOU: (\w+) proposes', user)
            d.update(to=m.group(1) if m else to, answer=random.choice(['accept', 'accept', 'decline']), body='ok')
        if act == 'review':
            m = re.search(r'id=(\w{6}) by', user); d.update(id=m.group(1))
        if act == 'gene_swap':
            d.update(**{'with': to})
        d['feel'] = {to: random.choice([-1, 0, 1, 2])}
        return json.dumps(d)
    if task == 'digest':
        return json.dumps(dict(title='Maize yields drop under drought', body='Results show a 12% change in 2024 according to [1] and [2], pointing to stress on yields.', confidence=0.7))
    if task == 'review':
        return json.dumps(dict(score=random.choice([4, 6, 7, 8, 9]), critique='Solid grounding.'))
    if task == 'innovate':
        return json.dumps(dict(title='Drought-tolerant seed exchange', problem='Smallholders lose yield in dry spells.', proposal='Set up a community seed exchange for drought tolerant maize varieties, tracked by SMS to match farms with proven seed lines.', first_step='Pilot in one chiefdom.', builds_on=[]))
llm.set_mock(mock)

store = get_store()
for i in range(160):
    r = world.tick()
    assert r['ok'], r
    if i == 80:   # force a season mid-run, and another at the end
        world.season(store, r['tick'], force=True)
world.season(store, r['tick'], force=True)

agents = store.select('soc_agents', order='born_tick')
print('ticks:', store.world_get('tick'))
print('alive:', [(a['name'], a['generation'], a['profession'] or '-', round(a['fitness'])) for a in agents if a['status'] == 'alive'])
print('retired:', [a['name'] for a in agents if a['status'] == 'retired'])
from collections import Counter
print('events:', Counter(e['type'] for e in store.select('soc_events')))
print('rel kinds:', Counter(r['kind'] for r in store.select('soc_relationships')))
print('findings:', Counter(f['kind'] for f in store.select('soc_findings')))
print('reviewed:', sum(1 for f in store.select('soc_findings') if f['review_count'] >= 2))
print('swaps:', [e['text'][:90] for e in store.select('soc_events', {'type': 'swap'})][:2])
print('births:', [e['text'][:110] for e in store.select('soc_events', {'type': 'birth'})])
errs = [e for e in store.select('soc_events') if e['type'] == 'error']
assert len(agents) >= 9

# ── API smoke test ───────────────────────────────────────────────────────────
from flask import Flask
from society import init_society
app = Flask(__name__)
class FakeSched:
    jobs = []
    def add_job(self, *a, **k): self.jobs.append((a, k))
sch = FakeSched(); init_society(app, sch)
assert sch.jobs and sch.jobs[0][1]['id'] == 'society_tick'
c = app.test_client()
st = c.get('/api/society/state').get_json(); print('state agents', len(st['agents']), 'rels', len(st['relationships']), 'tick', st['tick'])
ev = c.get('/api/society/events?limit=5').get_json()['events']; print('events', len(ev), ev[0]['name'], ev[0]['type'])
fi = c.get('/api/society/findings?limit=3').get_json()['findings']; print('findings', len(fi), fi[0]['name'], fi[0]['review_avg'])
aid = st['agents'][0]['id']; d = c.get(f'/api/society/agents/{aid}').get_json(); print('detail', d['agent']['name'], len(d['memories']), len(d['works']), len(d['relationships']))
r = c.post('/api/society/react', json={'finding_id': fi[0]['id'], 'reaction': 'agree'}); print('react', r.status_code, r.get_json())
r = c.post('/api/society/react', json={'finding_id': fi[0]['id'], 'reaction': 'agree'}); print('react dup', r.status_code)
print('admin no token', c.post('/api/society/admin/tick').status_code)
os.environ['SOC_ADMIN_TOKEN'] = 'secret'
print('admin bad', c.post('/api/society/admin/tick', headers={'X-Admin-Token': 'x'}).status_code)
print('admin ok', c.post('/api/society/admin/tick?wait=1', headers={'X-Admin-Token': 'secret'}).get_json()['ok'])
print('admin season', c.post('/api/society/admin/season', headers={'X-Admin-Token': 'secret'}).status_code)
# dormant mode: no job registered
os.environ['SOC_ENABLED'] = '0'
app2 = Flask(__name__); sch2 = FakeSched(); sch2.jobs = []; init_society(app2, sch2); print('dormant jobs', len(sch2.jobs))
# no-provider path returns fast
llm.set_mock(None); import time; t=time.time(); print('no-key call ->', llm.call('x','s','u'), round(time.time()-t,2),'s')
