"""
society/genome.py — what a citizen is made of, and how genes mix.

A genome = 8 personality traits (0..1) + an interest vector over the 8 domains.
Reproduction = crossover + mutation. Bonded citizens can also swap a trait
(horizontal exchange) without reproducing.
"""
import random
from .config import DOMAINS

TRAITS = ['curiosity', 'sociability', 'risk', 'agreeableness',
          'ambition', 'creativity', 'rigor', 'romance']

TRAIT_TEXT = {
    'curiosity':     ('incurious, prefers the familiar', 'endlessly curious, chases rabbit holes'),
    'sociability':   ('solitary, speaks only when it matters', 'craves company and conversation'),
    'risk':          ('cautious, hates gambles', 'bold, loves a gamble'),
    'agreeableness': ('blunt, argumentative, hard to please', 'warm, accommodating, avoids conflict'),
    'ambition':      ('content, unambitious', 'fiercely ambitious, wants to be the best'),
    'creativity':    ('literal and methodical', 'inventive, makes unusual connections'),
    'rigor':         ('loose with evidence, goes on gut feeling', 'sceptical, demands evidence for everything'),
    'romance':       ('guarded, not drawn to intimacy', 'a hopeless romantic, bonds deeply'),
}


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def normalize_interests(interests: dict) -> dict:
    vals = {d: max(0.02, float(interests.get(d, 0.0))) for d in DOMAINS}
    total = sum(vals.values())
    return {d: round(v / total, 4) for d, v in vals.items()}


def make_genome(traits: dict, interests: dict) -> dict:
    return {
        'traits': {t: round(clamp(float(traits.get(t, 0.5))), 3) for t in TRAITS},
        'interests': normalize_interests(interests),
    }


def random_genome(rng=random) -> dict:
    return make_genome(
        {t: rng.uniform(0.2, 0.85) for t in TRAITS},
        {d: rng.random() ** 2 for d in DOMAINS},
    )


def crossover(ga: dict, gb: dict, rng=random, sigma=0.07) -> dict:
    """Uniform crossover (with some blending) followed by gaussian mutation."""
    traits = {}
    for t in TRAITS:
        a, b = ga['traits'][t], gb['traits'][t]
        r = rng.random()
        v = a if r < 0.4 else b if r < 0.8 else (a + b) / 2
        if rng.random() < 0.5:
            v += rng.gauss(0, sigma)
        traits[t] = clamp(v)
    interests = {}
    for d in DOMAINS:
        a, b = ga['interests'][d], gb['interests'][d]
        v = a if rng.random() < 0.5 else b
        if rng.random() < 0.4:
            v += rng.gauss(0, 0.04)
        interests[d] = max(0.0, v)
    return make_genome(traits, interests)


def swap_trait(ga: dict, gb: dict, rng=random, pull=0.25):
    """Horizontal exchange: one trait in each genome moves toward the other's value."""
    t = rng.choice(TRAITS)
    a, b = ga['traits'][t], gb['traits'][t]
    na = clamp(a + pull * (b - a))
    nb = clamp(b + pull * (a - b))
    ga2 = {'traits': dict(ga['traits']), 'interests': dict(ga['interests'])}
    gb2 = {'traits': dict(gb['traits']), 'interests': dict(gb['interests'])}
    ga2['traits'][t] = round(na, 3)
    gb2['traits'][t] = round(nb, 3)
    return t, ga2, gb2


def describe(g: dict) -> str:
    """Turn a genome into personality sentences for the system prompt."""
    parts = []
    for t in TRAITS:
        v = g['traits'][t]
        if v >= 0.7:
            parts.append(TRAIT_TEXT[t][1])
        elif v <= 0.3:
            parts.append(TRAIT_TEXT[t][0])
    return '; '.join(parts) if parts else 'balanced and even-tempered'


def top_interests(g: dict, n=3):
    return [d for d, _ in sorted(g['interests'].items(), key=lambda kv: -kv[1])[:n]]
