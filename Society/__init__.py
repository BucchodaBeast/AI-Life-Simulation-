"""
Signal Society V2 — "the Society".

Nine artificial citizens with distinct voices, personalities and genomes. They choose what to
search, who to talk to, who to befriend or love, review each other's work, settle into
professions, and — through selection and reproduction — evolve across generations.

Honest framing: they are LLM-driven agents in an artificial-life simulation, not conscious beings.
The autonomy (free choice from a menu), memory, relationships and selection are all real mechanisms;
the consciousness is not claimed.

Hook it into the live app with three lines (see SOCIETY.md):
    from society import init_society
    init_society(app, scheduler)          # before scheduler.start()
"""
import logging
from datetime import datetime, timedelta

log = logging.getLogger('society')


def init_society(app, scheduler=None):
    """Registers the /api/society routes and (if SOC_ENABLED=1) the tick job. Never raises."""
    try:
        from . import config
        from .api import bp
        app.register_blueprint(bp)
        if config.enabled() and scheduler is not None:
            from . import world
            scheduler.add_job(
                world.tick_safe, 'interval', minutes=config.TICK_MINUTES, id='society_tick',
                max_instances=1, coalesce=True, misfire_grace_time=300,
                next_run_time=datetime.now() + timedelta(seconds=90))
            log.info(f'Society ACTIVE: tick every {config.TICK_MINUTES} min, '
                     f'{config.AGENTS_PER_TICK} citizens per tick')
        else:
            log.info('Society routes registered; simulation dormant (set SOC_ENABLED=1 to start it)')
    except Exception as e:                       # the live app must never fail because of the Society
        log.error(f'Society failed to initialise: {type(e).__name__}: {e}')
