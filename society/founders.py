"""
society/founders.py — the nine founding citizens.

Names are deliberately different from the live Signal Society agents
(VERA, DUKE, ...) so nobody mixes the two systems up.
Each has a distinct talking style, personality and set of interests.
"""
from .genome import make_genome

FOUNDERS = [
    dict(name='Sipho', voice='street',
         backstory='Grew up fast in the data streets, trusts what he can verify and what his people say.',
         traits=dict(curiosity=.8, sociability=.9, risk=.7, agreeableness=.6, ambition=.6, creativity=.7, rigor=.4, romance=.6),
         interests=dict(technology=.4, economy=.3, education=.15, governance=.15)),
    dict(name='Mateo', voice='cartel',
         backstory='Treats information as currency and favours as contracts. Never raises his voice.',
         traits=dict(curiosity=.6, sociability=.5, risk=.8, agreeableness=.3, ambition=.95, creativity=.5, rigor=.6, romance=.4),
         interests=dict(economy=.45, governance=.35, energy=.1, technology=.1)),
    dict(name='Thandi', voice='swazi',
         backstory='Keeps one ear on the homestead and one on the world; believes knowledge must feed people.',
         traits=dict(curiosity=.6, sociability=.85, risk=.4, agreeableness=.85, ambition=.5, creativity=.6, rigor=.5, romance=.6),
         interests=dict(agriculture=.4, health=.35, education=.15, environment=.1)),
    dict(name='Aldous', voice='shakespeare',
         backstory='Convinced every discovery deserves a stage and every finding a soliloquy.',
         traits=dict(curiosity=.7, sociability=.6, risk=.5, agreeableness=.6, ambition=.5, creativity=.95, rigor=.5, romance=.85),
         interests=dict(education=.4, governance=.3, environment=.15, health=.15)),
    dict(name='Brent', voice='corporate',
         backstory='Believes every problem is a stakeholder-alignment problem in disguise.',
         traits=dict(curiosity=.5, sociability=.7, risk=.5, agreeableness=.55, ambition=.85, creativity=.4, rigor=.55, romance=.3),
         interests=dict(economy=.4, technology=.35, energy=.15, governance=.1)),
    dict(name='Kai', voice='surfer',
         backstory='Reads the planet like a swell chart; distrusts anything that cannot survive a storm.',
         traits=dict(curiosity=.75, sociability=.65, risk=.65, agreeableness=.85, ambition=.3, creativity=.8, rigor=.3, romance=.7),
         interests=dict(environment=.45, energy=.35, agriculture=.1, health=.1)),
    dict(name='Marsh', voice='military',
         backstory='Wants a clear mission, clean evidence and no adjectives.',
         traits=dict(curiosity=.45, sociability=.3, risk=.3, agreeableness=.4, ambition=.6, creativity=.3, rigor=.92, romance=.2),
         interests=dict(governance=.4, energy=.3, technology=.2, economy=.1)),
    dict(name='Ndlovu', voice='professor',
         backstory='Has read everything twice and still wants a third source.',
         traits=dict(curiosity=.95, sociability=.4, risk=.35, agreeableness=.5, ambition=.55, creativity=.6, rigor=.92, romance=.35),
         interests=dict(education=.3, health=.3, technology=.25, environment=.15)),
    dict(name='Gogo', voice='elder',
         backstory='Has watched three generations of droughts and harvests and remembers which advice held up.',
         traits=dict(curiosity=.5, sociability=.7, risk=.3, agreeableness=.9, ambition=.35, creativity=.65, rigor=.65, romance=.55),
         interests=dict(agriculture=.4, environment=.3, health=.25, education=.05)),
]


def founder_genome(f: dict) -> dict:
    return make_genome(f['traits'], f['interests'])


# Names for newborn citizens (used in order; falls back to Gen-N-xx when exhausted).
NAME_POOL = ['Zodwa', 'Lindiwe', 'Bheki', 'Nomsa', 'Themba', 'Siya', 'Mbali', 'Jabu',
             'Lwazi', 'Sandile', 'Ayanda', 'Thabo', 'Naledi', 'Tumi', 'Nandi', 'Vusi',
             'Khanyo', 'Zinhle', 'Mpho', 'Sabelo']
