"""Start ScamShield Live.

    python run.py            # normal run
    python run.py --reload   # restart automatically when backend code changes
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import uvicorn  # noqa: E402

from app.api.main import create_app  # noqa: E402
from app.config import load_or_exit  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ScamShield Live server.")
    parser.add_argument("--reload", action="store_true", help="restart when backend code changes")
    args = parser.parse_args()

    settings = load_or_exit()  # fails fast with a friendly message before anything starts
    mode = "demo mode (no keys)" if settings.demo_mode else "live mode"
    print(f"\n  ScamShield Live, {mode}: open http://localhost:{settings.port}\n")

    if args.reload:
        uvicorn.run(
            "app.api.main:create_app",
            factory=True,
            host=settings.host,
            port=settings.port,
            reload=True,
            app_dir=str(BACKEND_DIR),
            reload_dirs=[str(BACKEND_DIR)],
        )
    else:
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
