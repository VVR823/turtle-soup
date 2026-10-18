import pytest

from app.test_server import fixture_settings


def test_api_fixture_retains_default_development_cors(tmp_path):
    settings = fixture_settings(tmp_path, {"TURTLE_SOUP_TESTING": "1"})
    assert settings.CORS_ORIGINS == ("http://localhost:3000", "http://127.0.0.1:3000")
    assert settings.TESTING and not settings.ALLOW_REAL_MODEL and settings.LLM_PROVIDER == "fake"


def test_explicit_ui_fixture_only_accepts_fixed_owned_loopback_origin(tmp_path):
    settings = fixture_settings(tmp_path, {"TURTLE_SOUP_TESTING": "1", "TURTLE_SOUP_UI_TESTING": "1"})
    assert settings.CORS_ORIGINS == ("http://127.0.0.1:18081",)


@pytest.mark.parametrize("environment", [
    {}, {"TURTLE_SOUP_TESTING": "0", "TURTLE_SOUP_UI_TESTING": "1"},
    {"TURTLE_SOUP_TESTING": "1", "TURTLE_SOUP_UI_TESTING": "anything"},
    {"TURTLE_SOUP_TESTING": "1", "TURTLE_SOUP_UI_ORIGIN": "https://example.com"},
])
def test_ui_cors_switch_cannot_expand_origins_or_escape_testing(tmp_path, environment):
    with pytest.raises(ValueError):
        fixture_settings(tmp_path, environment)
