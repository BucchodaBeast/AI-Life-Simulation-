"""
Signal Society — Flask entry point for the repository's Society/ package.
The repository folder is capitalized Society, so import it with that exact case.
"""
import logging
import os
from datetime import datetime

from flask import Flask, jsonify, send_from_directory
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


@app.get("/")
def index():
    """Serve the Society dashboard at the Render service's root URL."""
    return send_from_directory(app.root_path, "society.html")


@app.get("/health")
@app.get("/ping")
def health():
    return jsonify(ok=True, ts=datetime.utcnow().isoformat() + "Z")


try:
    from Society import init_society
    init_society(app, scheduler)
except Exception:
    log.exception("Society package failed to initialise")
    raise

if not scheduler.running:
    scheduler.start()
    log.info("Scheduler started; SOC_ENABLED=%s", os.environ.get("SOC_ENABLED", "0"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
