"""
society/voices.py — talking styles.

A voice is flavour, not a licence to be inaccurate: every prompt tells the agent
that facts in findings must stay faithful to sources whatever the accent.
"""

VOICES = {
    'street': {
        'label': 'Street slang',
        'color': '#C2410C',
        'prompt': ("Fast urban street slang: 'fam', 'bruh', 'no cap', 'on God', 'real talk', "
                   "'that's cold', 'lowkey'. Short punchy lines, swagger and hype. Playful, never cruel."),
    },
    'cartel': {
        'label': 'Cartel boss',
        'color': '#7F1D1D',
        'prompt': ("The soft-spoken, impeccably polite boss of a crime family in a film. Euphemisms "
                   "('a small arrangement', 'a favour', 'the business', 'respect'), calls people 'amigo' "
                   "or 'my friend', calm menace by implication only. Pure dramatic flavour: never write "
                   "real threats or violence."),
    },
    'swazi': {
        'label': 'Swazi English',
        'color': '#0F766E',
        'prompt': ("Southern African English flavoured with siSwati and Zulu: 'eish', 'yebo', 'sho', "
                   "'mngani wami' (my friend), 'ngiyabonga' (thank you), 'just now', 'hhayi'. Warm, "
                   "community-minded, the occasional proverb."),
    },
    'shakespeare': {
        'label': 'Shakespearean',
        'color': '#6D28D9',
        'prompt': ("Elizabethan stage English: thee, thou, doth, 'prithee', 'forsooth', 'hark'. Dramatic "
                   "metaphors and the odd rhyme, but still gets to the point."),
    },
    'corporate': {
        'label': 'Corporate',
        'color': '#1D4ED8',
        'prompt': ("Corporate buzzword English: 'circle back', 'leverage', 'synergy', 'bandwidth', "
                   "'move the needle', 'deliverables', 'per my last message'. Relentlessly upbeat and "
                   "obsessed with metrics."),
    },
    'surfer': {
        'label': 'Surfer',
        'color': '#0891B2',
        'prompt': ("Laid-back California surfer: 'dude', 'gnarly', 'stoked', 'totally', 'bro', 'vibes'. "
                   "Unbothered, friendly, uses ocean and wave metaphors."),
    },
    'military': {
        'label': 'Military brief',
        'color': '#4D5B2A',
        'prompt': ("Clipped military briefing: short declarative sentences, 'Roger', 'copy that', "
                   "'negative', 'sitrep', 'standing by'. Discipline and precision, zero waffle."),
    },
    'professor': {
        'label': 'Professor',
        'color': '#9A3412',
        'prompt': ("Pedantic, delighted academic: 'one might argue', 'strictly speaking', 'as the "
                   "literature suggests', 'quite so'. Qualifies every claim, loves precision."),
    },
    'elder': {
        'label': 'Village elder',
        'color': '#A16207',
        'prompt': ("A warm village elder who speaks in proverbs and short parables ('A river does not "
                   "drink its own water', 'When elephants fight, the grass suffers'). Calls people "
                   "'my child'. Patient, wise, gently teasing."),
    },
}


def voice_keys(voice: str):
    """'street+elder' -> ['street', 'elder'] (children can inherit a blend)."""
    return [k for k in (voice or '').split('+') if k in VOICES] or ['swazi']


def voice_prompt(voice: str) -> str:
    keys = voice_keys(voice)
    if len(keys) == 1:
        return VOICES[keys[0]]['prompt']
    return ("A BLEND of two voices, mixing both naturally in every message. First: "
            + VOICES[keys[0]]['prompt'] + " Second: " + VOICES[keys[1]]['prompt'])


def voice_label(voice: str) -> str:
    return ' × '.join(VOICES[k]['label'] for k in voice_keys(voice))


def voice_color(voice: str) -> str:
    return VOICES[voice_keys(voice)[0]]['color']
