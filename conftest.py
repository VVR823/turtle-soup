"""Repository-wide guards run before test-module collection, not after import."""
import os
import tempfile
from pathlib import Path

import pytest

from testing.guards import NetworkGuard, protect_runtime_files, validate_basetemp


def pytest_addoption(parser):
    parser.addoption("--real-model", action="store_true", help="Explicit real-model opt-in")
    parser.addoption("--online", action="store_true", help="Explicit deployed-service opt-in")


def pytest_configure(config):
    patch = pytest.MonkeyPatch()
    config._turtle_patch = patch
    try:
        if config.option.basetemp is None:
            # Do not borrow the desktop user's temp tree (different Windows SID).
            parent = Path(__file__).resolve().parent / ".cache" / "pytest"
            validate_basetemp(parent / "new-placeholder", Path(__file__).resolve().parent)
            parent.mkdir(parents=True, exist_ok=True)
            config.option.basetemp = tempfile.mkdtemp(prefix="run-", dir=parent)
        try:
            config.option.basetemp = str(validate_basetemp(
                Path(config.option.basetemp), Path(__file__).resolve().parent,
            ))
        except ValueError as error:
            raise pytest.UsageError(str(error)) from error
        # Fake LangChain runs must not send traces to a cloud telemetry service.
        patch.setenv("LANGSMITH_TRACING", "false")
        patch.setenv("LANGCHAIN_TRACING_V2", "false")
        patch.delenv("LANGSMITH_API_KEY", raising=False)
        patch.delenv("LANGCHAIN_API_KEY", raising=False)
        real = config.getoption("--real-model")
        online = config.getoption("--online")
        if real and os.getenv("TURTLE_SOUP_REAL_MODEL_CONFIRMED_FREE") != "1":
            raise pytest.UsageError("--real-model requires TURTLE_SOUP_REAL_MODEL_CONFIRMED_FREE=1")
        if not real:
            for name in ("OPENAI_API_KEY", "QWEN_API_KEY", "SILICONFLOW_API_KEY", "ZHIPU_API_KEY"):
                patch.delenv(name, raising=False)
        if not real and not online:
            guard = NetworkGuard()
            guard.install(patch)
            config._turtle_network_guard = guard
        protect_runtime_files(patch, Path(__file__).resolve().parent)
    except BaseException:
        patch.undo()
        raise


def pytest_collection_modifyitems(config, items):
    for item in items:
        for marker, option in (("real_model", "--real-model"), ("online", "--online")):
            if item.get_closest_marker(marker) and not config.getoption(option):
                item.add_marker(pytest.mark.skip(reason=f"Explicit {option} opt-in required"))


def pytest_unconfigure(config):
    patch = getattr(config, "_turtle_patch", None)
    if patch is not None:
        patch.undo()
