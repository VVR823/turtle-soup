"""Owned single-worker launcher; --check validates without starting any service."""
import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import load_settings


def build_launch_config(settings):
    if settings.API_WORKER_COUNT != 1:
        raise ValueError("This launcher requires exactly one API worker")
    return {"app": "app.main:app", "host": "127.0.0.1", "port": 8000,
            "workers": 1, "proxy_headers": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate config; do not start the server")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        options = build_launch_config(settings)
    except ValueError:
        print(json.dumps({"valid": False, "code": "launch_configuration_invalid"}))
        return 2
    if args.check:
        print(json.dumps({"valid": True, "workers": options["workers"], "agentEnabled": settings.ENABLE_AGENT,
                          "proxyHeaders": False, "deploymentVerified": False}))
        return 0
    # Executed only by an explicit operator launch. The app still owns its
    # lifecycle/config/schema checks; this does not initialize Agent workers.
    import uvicorn
    uvicorn.run(**options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
