"""Starting points, so a first strategy is edited rather than typed from blank.

Each is a well-known rule set, written out exactly as the builder would store
it. None is a recommendation: they are here because they are easy to read, and
every one of them goes through the same gate as anything else.
"""

from __future__ import annotations

from eulerlab.builder.spec import BuilderSpec


def _ind(name: str, **params: float) -> dict[str, object]:
    return {"kind": "indicator", "name": name, "params": params}


def _val(value: float) -> dict[str, object]:
    return {"kind": "value", "value": value}


RAW: list[dict[str, object]] = [
    {
        "name": "Golden cross",
        "description": "Trend following: own a name while its 50-day average is above its 200-day.",
        "universe": {"universe": "nifty100"},
        "entry": {
            "rules": [
                {
                    "left": _ind("sma", period=50),
                    "op": "crosses_above",
                    "right": _ind("sma", period=200),
                }
            ]
        },
        "exit": {
            "rules": [
                {
                    "left": _ind("sma", period=50),
                    "op": "crosses_below",
                    "right": _ind("sma", period=200),
                }
            ]
        },
        "sizing": {"max_positions": 10},
        "risk": {"stop_loss_pct": 15},
    },
    {
        "name": "RSI dip buy",
        "description": "Mean reversion in an uptrend: buy a short-term oversold reading above the 200-day average.",
        "universe": {"universe": "nifty100"},
        "entry": {
            "match": "all",
            "rules": [
                {"left": _ind("rsi", period=2), "op": "below", "right": _val(10)},
                {"left": _ind("close"), "op": "above", "right": _ind("sma", period=200)},
            ],
        },
        "exit": {"rules": [{"left": _ind("rsi", period=2), "op": "above", "right": _val(70)}]},
        "sizing": {"max_positions": 10},
        "risk": {"stop_loss_pct": 8, "max_hold_days": 10},
    },
    {
        "name": "Momentum top 20",
        "description": "Hold the 20 strongest names by 6-month return, while they stay above their 100-day average.",
        "universe": {"universe": "nifty250", "min_turnover": 50_000_000},
        "entry": {
            "rules": [
                {"left": _ind("roc", period=126), "op": "above", "right": _val(0)},
                {"left": _ind("close"), "op": "above", "right": _ind("sma", period=100)},
            ]
        },
        "exit": {
            "rules": [{"left": _ind("close"), "op": "below", "right": _ind("sma", period=100)}]
        },
        "sizing": {
            "max_positions": 20,
            "ranking": {"by": _ind("roc", period=126), "order": "highest"},
        },
        "risk": {"trailing_stop_pct": 20},
    },
    {
        "name": "52-week breakout",
        "description": "Buy a close above the previous year's high on above-average volume; trail a stop.",
        "universe": {"universe": "nifty250"},
        "entry": {
            "rules": [
                {
                    "left": _ind("close"),
                    "op": "crosses_above",
                    "right": _ind("donchian_high", period=252),
                },
                {
                    "left": _ind("volume"),
                    "op": "above",
                    "right": {**_ind("volume_sma", period=50), "multiplier": 1.5},
                },
            ]
        },
        "exit": {
            "rules": [
                {"left": _ind("close"), "op": "below", "right": _ind("donchian_low", period=50)}
            ]
        },
        "sizing": {"max_positions": 10, "method": "volatility_scaled"},
        "risk": {"trailing_stop_pct": 12},
    },
]

TEMPLATES: list[BuilderSpec] = [BuilderSpec.model_validate(raw) for raw in RAW]
