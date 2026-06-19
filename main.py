"""Boon Academy — single entry point.

One command, no setup steps:

    python main.py

It self-bootstraps dependencies (installs requirements.txt if anything is
missing), runs the pipeline once to populate state, then starts the FastAPI
dashboard server. The pipeline can also be re-run on demand from the dashboard
(POST /api/pipeline/run). Pipeline logic lives in pipeline.py.
"""

# --- stdlib only above the dependency bootstrap -------------------------------
import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)

# Import name -> pip install target. Bootstrapped on first run so the whole
# system comes up from a fresh clone with nothing but `python main.py`.
REQUIRED_PACKAGES = {
    "pandas": "pandas",
    "uvicorn": "uvicorn[standard]",
    "dotenv": "python-dotenv",
    "fastapi": "fastapi",
    "sqlalchemy": "sqlalchemy",
    "jinja2": "jinja2",
    "anthropic": "anthropic",
}


def ensure_dependencies() -> None:
    """Install any missing third-party packages from requirements.txt."""
    import importlib.util

    missing = [m for m in REQUIRED_PACKAGES if importlib.util.find_spec(m) is None]
    if not missing:
        return
    req = os.path.join(os.path.dirname(__file__), "requirements.txt")
    target = ["-r", req] if os.path.exists(req) else [REQUIRED_PACKAGES[m] for m in missing]
    print(f"Installing missing dependencies: {', '.join(missing)} ...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *target])


# Bootstrap before importing anything third-party, so a fresh clone runs with
# nothing but `python main.py`.
ensure_dependencies()

import uvicorn  # noqa: E402 — must follow the dependency bootstrap
from dotenv import load_dotenv  # noqa: E402

from models import init_db  # noqa: E402
from pipeline import run_pipeline  # noqa: E402


def setup_logging() -> None:
    """Configure root logging at INFO with a consistent format."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main():
    """Bootstrap, run the pipeline once, then start the dashboard server."""
    load_dotenv()
    setup_logging()
    init_db()
    run_pipeline()

    port = int(os.getenv("PORT", "8000"))
    logger.info("Starting dashboard at http://localhost:%d", port)
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
