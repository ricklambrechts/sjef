import pytest

from sjef import config
from sjef.selftest import run_selftest


@pytest.mark.parametrize("contents", [None, b"weekly: [", b"\xff"])
def test_config_load_failure_returns_nonzero(tmp_path, monkeypatch, capsys, contents):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    if contents is not None:
        (tmp_path / "config.yaml").write_bytes(contents)

    assert run_selftest() == 1

    output = capsys.readouterr().out
    assert "❌" in output
    assert "config.yaml" in output
    assert "Alles groen" not in output
