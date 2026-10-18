"""Explicit local worker policy; never start a server or inspect live units."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.config import Settings, load_settings


@pytest.mark.parametrize("count", [0, -1, True, "2"])
def test_invalid_worker_count_cannot_enter_runtime(tmp_path, count):
    with pytest.raises(ValueError):
        Settings.for_test(tmp_path, API_WORKER_COUNT=count)


def test_agent_requires_single_declared_api_worker(tmp_path):
    with pytest.raises(ValueError):
        Settings.for_test(tmp_path, API_WORKER_COUNT=2, ENABLE_AGENT=True)
    assert Settings.for_test(tmp_path, API_WORKER_COUNT=1, ENABLE_AGENT=True).API_WORKER_COUNT == 1
    assert Settings.for_test(tmp_path).ENABLE_AGENT is False


def test_worker_count_environment_is_parsed_as_an_integer_without_dotenv(tmp_path):
    values = {"TURTLE_SOUP_TESTING": "1", "TURTLE_SOUP_DATA_DIR": str(tmp_path),
              "API_WORKER_COUNT": "2", "ENABLE_AGENT": "0"}
    assert load_settings(environ=values, load_env=False).API_WORKER_COUNT == 2
    with pytest.raises(ValueError):
        load_settings(environ={**values, "ENABLE_AGENT": "1"}, load_env=False)
    with pytest.raises(ValueError):
        load_settings(environ={**values, "API_WORKER_COUNT": "not-an-integer"}, load_env=False)


def launcher():
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("owned_launch_policy", root / "scripts/run-backend.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return root, module


def test_owned_launcher_selects_one_worker_and_preserves_real_peer_for_app_policy(tmp_path):
    _, module = launcher()
    options = module.build_launch_config(Settings.for_test(tmp_path))
    assert options["workers"] == 1
    assert options["host"] == "127.0.0.1"
    assert options["proxy_headers"] is False
    with pytest.raises(ValueError):
        module.build_launch_config(Settings.for_test(tmp_path, API_WORKER_COUNT=2))


def test_check_mode_does_not_start_server_create_data_or_print_secrets(tmp_path):
    root, _ = launcher()
    selected = tmp_path / "uncreated-data"
    env = {**os.environ, "TURTLE_SOUP_TESTING": "1", "TURTLE_SOUP_DATA_DIR": str(selected),
           "API_WORKER_COUNT": "1", "ENABLE_AGENT": "0", "ADMIN_TOKEN": "synthetic-private-admin"}
    response = subprocess.run([sys.executable, str(root / "scripts/run-backend.py"), "--check"],
                              env=env, capture_output=True, text=True, timeout=5)
    assert response.returncode == 0, response.stderr
    report = json.loads(response.stdout)
    assert report["workers"] == 1 and report["deploymentVerified"] is False
    assert "synthetic-private-admin" not in response.stdout + response.stderr
    assert not selected.exists()
