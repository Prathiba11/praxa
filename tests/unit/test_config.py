import pytest

from career_copilot.core.config import Settings, get_settings
from career_copilot.core.errors import ConfigError

GOOD_ENV = {
    "OPENROUTER_API_KEY": "sk-or-v1-fake-key-for-tests",
    "CC_MODEL": "openai/gpt-4o-mini",
}


@pytest.fixture(autouse=True)
def _clear_cache():
    """get_settings is lru_cached - stale objects would leak between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _settings(**overrides: str) -> Settings:
    """Build Settings from explicit values, ignoring the real .env on disk."""
    return Settings(_env_file=None, **{**GOOD_ENV, **overrides})  # type: ignore[arg-type]


def test_loads_from_environment():
    s = _settings()
    assert s.chat_model == "openai/gpt-4o-mini"
    assert s.openrouter_base_url == "https://openrouter.ai/api/v1"


def test_missing_api_key_raises():
    with pytest.raises(ConfigError):
        _settings(OPENROUTER_API_KEY="")


def test_placeholder_key_raises():
    with pytest.raises(ConfigError):
        _settings(OPENROUTER_API_KEY="sk-or-v1-replace-me")


def test_empty_model_raises():
    with pytest.raises(ConfigError):
        _settings(CC_MODEL="")


def test_unknown_embed_provider_raises():
    with pytest.raises(ConfigError):
        _settings(CC_EMBED_PROVIDER="pinecone")


def test_repr_does_not_leak_the_key():
    assert "fake-key" not in repr(_settings())
