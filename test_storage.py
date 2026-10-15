"""Tests for storage.py (local mode; the GitHub branch needs network)."""
import storage


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(storage, "LEGACY_STOCKS", tmp_path / "portfolio.csv")


def test_save_then_load_roundtrip(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    assert storage.load("etf", None) is None
    storage.save("etf", b"Symbol\nA\n", None)
    assert storage.load("etf", None) == b"Symbol\nA\n"
    storage.save("etf", b"Symbol\nB\n", None)  # a new upload replaces the old one
    assert storage.load("etf", None) == b"Symbol\nB\n"


def test_legacy_portfolio_csv_is_the_stocks_fallback(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    (tmp_path / "portfolio.csv").write_bytes(b"old")
    assert storage.load("stocks", None) == b"old"
    assert storage.load("crypto", None) is None
    storage.save("stocks", b"new", None)
    assert storage.load("stocks", None) == b"new"


def test_github_config_requires_token_and_repo():
    assert storage.github_config({}) is None
    assert storage.github_config({"github_token": "t"}) is None
    cfg = storage.github_config({"github_token": "t", "github_repo": "o/r"})
    assert cfg.path("crypto") == "data/crypto.csv" and cfg.branch == "main"
