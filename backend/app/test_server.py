"""Local Playwright fixture server. Never use this entry point for production."""
import os
import sys
import threading
from pathlib import Path
from uuid import uuid4

from fastapi import Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class FixtureSuspension(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    sessionId: str = Field(min_length=1, max_length=200)
    suspended: bool


class FixtureCorpusAvailability(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    available: bool


def fixture_settings(data_dir, environment):
    """Only the explicit test entry point may opt in to the fixed UI origin."""
    from .config import Settings
    if environment.get("TURTLE_SOUP_TESTING") != "1":
        raise ValueError("Fixture requires explicit testing mode")
    ui_mode = environment.get("TURTLE_SOUP_UI_TESTING")
    if ui_mode not in (None, "1") or "TURTLE_SOUP_UI_ORIGIN" in environment:
        raise ValueError("UI fixture origin is fixed; arbitrary overrides are forbidden")
    options = dict(ADMIN_TOKEN="e2e-test-only", TEST_INSTANCE_ID=environment.get("TURTLE_SOUP_TEST_INSTANCE_ID", ""))
    if ui_mode == "1":
        options["CORS_ORIGINS"] = ("http://127.0.0.1:18081",)
    return Settings.for_test(Path(data_dir), **options)


def fixture_app(settings, *, ui_testing):
    from .main import create_app
    if (type(ui_testing) is not bool or not settings.TESTING
        or settings.ALLOW_REAL_MODEL or settings.LLM_PROVIDER != "fake"
        or (ui_testing and not settings.TEST_INSTANCE_ID)):
        raise ValueError("Fixture requires isolated fake testing settings and owned UI nonce")
    if not ui_testing:
        return create_app(settings)
    from dataclasses import replace
    from testing.ui_agent_fixture import prepare_ui_agent
    from .testing import SyntheticRepairModel
    soups, corpus, draft = prepare_ui_agent(settings)
    application = create_app(replace(settings, ENABLE_AGENT=True), model=SyntheticRepairModel(draft),
        soups=soups, repair_corpus=corpus)

    @application.post("/testing/corpus-availability")
    def select_owned_fixture_corpus(body: FixtureCorpusAvailability,
        x_test_instance_id: str | None = Header(default=None)):
        import hmac
        if x_test_instance_id is None or not hmac.compare_digest(
            x_test_instance_id.encode(), settings.TEST_INSTANCE_ID.encode()
        ):
            raise HTTPException(403, "Owned fixture nonce required")
        runtime = application.state.runtime
        if runtime is None or runtime.closed:
            raise HTTPException(503, "Owned fixture is not live")
        # This test entry already requires fake TESTING+UI+nonce. No caller
        # path, labels or replacement corpus; only withdraw/restore its source.
        runtime.repair_corpus = corpus if body.available else None
        return {"available": runtime.repair_corpus is not None}

    @application.post("/testing/rule-suspension")
    def suspend_owned_fixture(body: FixtureSuspension, x_test_instance_id: str | None = Header(default=None)):
        import hmac
        from . import db
        from .rule_publication import RulePublisher, RulePublicationError
        if x_test_instance_id is None or not hmac.compare_digest(
            x_test_instance_id.encode(), settings.TEST_INSTANCE_ID.encode()
        ):
            raise HTTPException(403, "Owned fixture nonce required")
        session = db.get_session(body.sessionId)
        if session is None:
            raise HTTPException(404, "Fixture session not found")
        rule_version = session["ruleVersion"]
        conn = db._connect()
        try:
            row = conn.execute("SELECT row_version FROM runtime_meta WHERE key=?",
                ("rule_suspension:" + rule_version[3:],)).fetchone()
            expected = None if row is None else row[0]
        finally:
            conn.close()

        def deny_publication(*args, **kwargs):
            raise RulePublicationError("fixture_publication_forbidden", 403)

        RulePublisher(authorizer=deny_publication).set_rule_suspension(rule_version,
            expected_marker_version=expected, suspended=body.suspended,
            reason="Synthetic owned UI suspension scenario", operation_key=str(uuid4()))
        return {"ok": True}

    return application


def main():
    if os.environ.get("TURTLE_SOUP_TESTING") != "1" or not os.environ.get("TURTLE_SOUP_DATA_DIR"):
        raise RuntimeError("Test server requires explicit testing mode and temporary storage")
    # Disable tracing before importing LangChain, independent of inherited env.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    for key in ("OPENAI_API_KEY", "QWEN_API_KEY", "SILICONFLOW_API_KEY", "ZHIPU_API_KEY", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"):
        os.environ.pop(key, None)
    import pytest
    import uvicorn
    from testing.guards import NetworkGuard, protect_runtime_files
    patch = pytest.MonkeyPatch()
    NetworkGuard().install(patch)
    protect_runtime_files(patch, Path(__file__).resolve().parents[2])
    try:
        settings = fixture_settings(Path(os.environ["TURTLE_SOUP_DATA_DIR"]), os.environ)
        class FixtureServer(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if self.started:
                    print(f"TS01_READY:{settings.TEST_INSTANCE_ID}", flush=True)

        server = FixtureServer(uvicorn.Config(
            fixture_app(settings, ui_testing=os.environ.get("TURTLE_SOUP_UI_TESTING") == "1"),
            host="127.0.0.1", port=18080, access_log=False,
        ))
        def stop_on_parent_close():
            # A pipe EOF is portable and reaches the real Windows interpreter.
            # It also stops the fixture if its owner crashes, without killing other PIDs.
            for _ in sys.stdin:
                pass
            server.should_exit = True

        threading.Thread(target=stop_on_parent_close, daemon=True).start()
        server.run()
    finally:
        patch.undo()


if __name__ == "__main__":
    main()
