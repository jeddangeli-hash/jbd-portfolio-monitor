"""Tests for the batched quote path in prices.py (Yahoo is mocked)."""
import pandas as pd
import pytest

import prices as pr


@pytest.mark.parametrize("sym,ccy", [
    ("AMZN", "USD"), ("RACE.MI", "EUR"), ("DE000A0SMU87.SG", "EUR"),
    ("BTC-USD", "USD"), ("EURUSD=X", "USD"), ("IT0005648255", None), ("VOD.L", None),
])
def test_guess_currency(sym, ccy):
    assert pr.guess_currency(sym) == ccy


def _download_frame(closes: dict[str, list[float]]) -> pd.DataFrame:
    idx = pd.date_range("2026-10-12", periods=3, freq="D")
    cols = pd.MultiIndex.from_tuples([(s, f) for s in closes for f in ("Open", "Close")])
    data = {(s, f): v for s, v in closes.items() for f in ("Open", "Close")}
    return pd.DataFrame(data, index=idx, columns=cols)


def test_fetch_quotes_batches_and_falls_back(monkeypatch):
    calls = {"download": 0, "one": []}

    def fake_download(tickers, **kw):
        calls["download"] += 1
        assert set(tickers.split()) == {"AMZN", "RACE.MI", "GONE"}  # IT… ISIN not batched
        return _download_frame({"AMZN": [10.0, 11.0, 12.0], "RACE.MI": [300.0, 310.0, 320.0]})

    def fake_one(sym):
        calls["one"].append(sym)
        return sym, ({"price": 102.0, "prev_close": 101.0, "currency": "EUR"}
                     if sym == "IT0005648255" else None)

    monkeypatch.setattr(pr.yf, "download", fake_download)
    monkeypatch.setattr(pr, "_quote_one", fake_one)
    q = pr.fetch_quotes(["AMZN", "RACE.MI", "GONE", "IT0005648255"])

    assert calls["download"] == 1
    assert q["AMZN"] == {"price": 12.0, "prev_close": 11.0, "currency": "USD"}
    assert q["RACE.MI"]["currency"] == "EUR" and q["RACE.MI"]["price"] == 320.0
    assert q["IT0005648255"]["price"] == 102.0          # slow path
    assert "GONE" not in q                               # no data anywhere
    assert sorted(calls["one"]) == ["GONE", "IT0005648255"]


def test_fetch_quotes_survives_download_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network")
    monkeypatch.setattr(pr.yf, "download", boom)
    monkeypatch.setattr(pr, "_quote_one", lambda s: (s, {"price": 1.0, "prev_close": 1.0, "currency": "USD"}))
    assert set(pr.fetch_quotes(["AMZN", "TSLA"])) == {"AMZN", "TSLA"}
