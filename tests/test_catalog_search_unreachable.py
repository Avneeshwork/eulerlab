"""A mixed instrument search survives one class whose files cannot be read."""

from __future__ import annotations

import pytest

from eulerlab.ingest import landing_reader
from eulerlab.strategies import AssetClass, catalog
from eulerlab.strategies.catalog import Instrument


def _one(symbol: str, asset_class: AssetClass) -> list[Instrument]:
    return [
        Instrument(symbol=symbol, asset_class=asset_class, has_daily=True, has_minute=False, rank=1)
    ]


def test_an_unreachable_class_is_left_out_not_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(query: str, limit: int) -> list[Instrument]:
        raise landing_reader.CloudUnavailable("B2_KEY_ID and B2_APP_KEY must be set")

    monkeypatch.setattr(
        catalog,
        "_supported_classes",
        lambda: {AssetClass.CRYPTO.value, AssetClass.MUTUAL_FUND.value},
    )
    monkeypatch.setattr(
        catalog, "crypto_instruments", lambda q, n: _one("BTCUSDT", AssetClass.CRYPTO)
    )
    monkeypatch.setattr(catalog, "fund_instruments", unreachable)

    found = catalog.search("", limit=10)

    assert [i.symbol for i in found] == ["BTCUSDT"]


def test_asking_for_the_unreachable_class_still_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(query: str, limit: int) -> list[Instrument]:
        raise landing_reader.CloudUnavailable("no bucket")

    monkeypatch.setattr(catalog, "fund_instruments", unreachable)

    with pytest.raises(landing_reader.CloudUnavailable):
        catalog.search("", asset_class=AssetClass.MUTUAL_FUND.value, limit=10)
