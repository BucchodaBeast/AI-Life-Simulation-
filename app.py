"""
Signal Society — compatible Flask entry point for the repository's Society/ package.

This entry point intentionally loads the Society V2 simulation that exists in the
repository. It does not import the absent legacy `agents.*` package.
"""
import logging
import os
from datetime import datetime

from flask import Flask, jsonify
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(message)s",
)
log = logging.getLogger("signal-society")

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

scheduler = BackgroundScheduler(timezone="UTC")


@app.get("/health")
@app.get("/ping")
def health():
    return jsonify(ok=True, ts=datetime.utcnow().isoformat() + "Z")


# The repository contains Society/ (capital S), not the old agents/ package.
# Relative imports inside Society continue to work when loaded as a package.
try:
    from Society import init_society
    init_society(app, scheduler)
except Exception:
    log.exception("Society package failed to initialise")
    raise

if not scheduler.running:
    scheduler.start()
    log.info("Scheduler started; Society simulation remains dormant unless SOC_ENABLED=1")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
