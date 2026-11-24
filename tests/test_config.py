import pytest

import config

VALID = {"MEXC_API_KEY": "abc123", "MEXC_API_SECRET": "sec456"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # Keep the developer's real .env and shell variables out of the tests.
    monkeypatch.setattr(config, "load_dotenv", lambda **kwargs: None)
    for name in ("MEXC_API_KEY", "MEXC_API_SECRET", "TRADING_MODE", "LIVE_TRADING"):
        monkeypatch.delenv(name, raising=False)


def set_env(monkeypatch, **values):
    for name, value in {**VALID, **values}.items():
        monkeypatch.setenv(name, value)


def test_paper_defaults(monkeypatch):
    set_env(monkeypatch)
    cfg = config.load_config()
    assert cfg.trading_mode == "paper"
    assert cfg.live_trading is False


def test_live_requires_both_flags(monkeypatch):
    set_env(monkeypatch, TRADING_MODE="live", LIVE_TRADING="true")
    cfg = config.load_config()
    assert cfg.trading_mode == "live"
    assert cfg.live_trading is True


@pytest.mark.parametrize("mode,live", [("live", "false"), ("paper", "true")])
def test_contradictory_flags_rejected(monkeypatch, mode, live):
    set_env(monkeypatch, TRADING_MODE=mode, LIVE_TRADING=live)
    with pytest.raises(RuntimeError, match="disagree"):
        config.load_config()


def test_invalid_mode_rejected(monkeypatch):
    set_env(monkeypatch, TRADING_MODE="yolo")
    with pytest.raises(RuntimeError, match="Invalid TRADING_MODE"):
        config.load_config()


def test_invalid_live_flag_rejected(monkeypatch):
    set_env(monkeypatch, LIVE_TRADING="yes")
    with pytest.raises(RuntimeError, match="Invalid LIVE_TRADING"):
        config.load_config()


@pytest.mark.parametrize("name", ["MEXC_API_KEY", "MEXC_API_SECRET"])
def test_missing_or_blank_credential_rejected(monkeypatch, name):
    set_env(monkeypatch, **{name: "   "})
    with pytest.raises(RuntimeError, match=f"{name} is missing"):
        config.load_config()


def test_placeholder_credential_rejected(monkeypatch):
    set_env(monkeypatch, MEXC_API_KEY="your_api_key_here")
    with pytest.raises(RuntimeError, match="placeholder"):
        config.load_config()


def test_secrets_hidden_from_repr(monkeypatch):
    set_env(monkeypatch)
    text = repr(config.load_config())
    assert "abc123" not in text and "sec456" not in text


def test_import_has_no_side_effects(capsys):
    import importlib

    importlib.reload(config)
    assert capsys.readouterr().out == ""
