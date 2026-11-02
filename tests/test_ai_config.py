import pytest

from sjef import config


@pytest.mark.parametrize(
    "value, expected",
    [(None, False), ("", False), ("   ", False), ("test-private-key", True)],
)
def test_only_anthropic_key_presence_is_exposed(monkeypatch, value, expected):
    monkeypatch.setattr(config, "load_dotenv", lambda *args: None)
    if value is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", value)
    secrets = config.Secrets.load()
    assert secrets.anthropic_key_configured is expected
    assert "test-private-key" not in repr(secrets)
