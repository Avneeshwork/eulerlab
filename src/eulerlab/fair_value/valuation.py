"""Explainable Indian equity fair-value prototype, built only from held data."""

from __future__ import annotations

import hashlib
import json
import statistics
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

from eulerlab.fair_value import factors
from eulerlab.paths import data_path

MODEL_VERSION = "india-common-residual-income-v4.1"
INDIA_ERP = 0.06920182533929162
INDIA_ERP_AS_OF = "2026-07-01"
SNAPSHOTS = data_path("derived/fair_value")
EXPLICIT_YEARS = 10
ROE_ANCHOR_YEARS = 5


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _row(table: dict[str, Any], labels: tuple[str, ...]) -> list[float | None]:
    for row in table.get("rows", []):
        if str(row.get("label", "")).strip().lower() in {label.lower() for label in labels}:
            return [_number(value) for value in row.get("values", [])]
    return []


def _period_values(table: dict[str, Any], labels: tuple[str, ...]) -> dict[str, float]:
    wanted = {label.lower() for label in labels}
    periods = table.get("periods", [])
    for row in table.get("rows", []):
        if str(row.get("label", "")).strip().lower() not in wanted:
            continue
        return {
            str(period): number
            for period, raw in zip(periods, row.get("values", []), strict=False)
            if (number := _number(raw)) is not None
        }
    return {}


def _historical_roe(tables: dict[str, Any]) -> list[tuple[str, float]]:
    """Annual ROE from net profit and average reported shareholders' equity."""
    profits = _period_values(tables.get("profit-loss", {}), ("Net Profit",))
    capital = _period_values(tables.get("balance-sheet", {}), ("Equity Capital",))
    reserves = _period_values(tables.get("balance-sheet", {}), ("Reserves", "Other Equity"))
    equity = {day: value + reserves.get(day, 0.0) for day, value in capital.items()}
    periods = sorted(day for day in profits if day in equity)
    result: list[tuple[str, float]] = []
    for prior, current in pairwise(periods):
        if current[:4].isdigit() and prior[:4].isdigit() and int(current[:4]) - int(prior[:4]) != 1:
            continue
        average_equity = (equity[prior] + equity[current]) / 2
        if average_equity > 0:
            roe = profits[current] / average_equity
            result.append((current, roe))
    return result


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _multistage_residual_income(
    book_value: float,
    current_roe: float,
    anchor_roe: float,
    payout: float,
    rate: float,
    *,
    years: int = EXPLICIT_YEARS,
    risk_free: float = 0.0,
    terminal_mode: str = "fade_to_cost_of_equity",
) -> dict[str, Any]:
    """Common clean-surplus model with explicit, named ROE persistence cases."""
    persistent = terminal_mode == "persistent_excess_returns"
    if rate <= 0:
        return {
            "value": 0.0,
            "year_5_roe_anchor": anchor_roe,
            "long_run_roe": anchor_roe if persistent else rate,
            "terminal_growth": 0.0,
            "terminal_payout": 1.0,
            "terminal_book_value": book_value,
            "terminal_value": 0.0,
            "year_1_eps": current_roe * book_value,
            "year_5_eps": anchor_roe * book_value,
            "year_10_eps": rate * book_value,
            "year_1_roe": current_roe,
            "year_5_roe": anchor_roe,
            "year_10_roe": rate,
            "explicit_years": years,
            "terminal_mode": terminal_mode,
        }
    anchor_years = min(ROE_ANCHOR_YEARS, years)
    book = book_value
    value = book_value
    eps_path: list[float] = []
    roe_path: list[float] = []
    for year in range(1, years + 1):
        if year <= anchor_years:
            roe = current_roe + (anchor_roe - current_roe) * year / anchor_years
        else:
            fade = (year - anchor_years) / (years - anchor_years)
            roe = anchor_roe + (rate - anchor_roe) * fade
        earnings = roe * book
        residual = earnings - rate * book
        value += residual / (1 + rate) ** year
        book += earnings * (1 - payout)
        eps_path.append(earnings)
        roe_path.append(roe)

    if persistent and anchor_roe > rate:
        stable_growth = max(
            0.0,
            min(anchor_roe * (1 - payout), risk_free, rate * (1 - 1e-6)),
        )
        stable_payout = max(0.0, min(1.0, 1 - stable_growth / anchor_roe))
        next_residual = (anchor_roe - rate) * book
        terminal_value = next_residual / (rate - stable_growth) if rate > stable_growth else 0.0
        value += terminal_value / (1 + rate) ** years
        long_run_roe = anchor_roe
    else:
        # Central and lower cases converge to zero abnormal income by year 10.
        stable_growth = max(
            0.0,
            min(rate * (1 - payout), risk_free, rate * (1 - 1e-6)),
        )
        stable_payout = max(0.0, min(1.0, 1 - stable_growth / rate))
        terminal_value = 0.0
        long_run_roe = rate
    return {
        "value": value,
        "year_5_roe_anchor": anchor_roe,
        "long_run_roe": long_run_roe,
        "terminal_growth": stable_growth,
        "terminal_payout": stable_payout,
        "terminal_book_value": book,
        "terminal_value": terminal_value,
        "year_1_eps": eps_path[0],
        "year_5_eps": eps_path[min(anchor_years, len(eps_path)) - 1],
        "year_10_eps": anchor_roe * book
        if persistent and long_run_roe == anchor_roe
        else eps_path[-1],
        "year_1_roe": roe_path[0],
        "year_5_roe": roe_path[min(anchor_years, len(roe_path)) - 1],
        "year_10_roe": long_run_roe,
        "explicit_years": years,
        "terminal_mode": "persistent_excess_returns"
        if persistent and anchor_roe > rate
        else "fade_to_cost_of_equity",
    }


def _earnings_anchor(
    eps: float,
    book_value: float,
) -> tuple[float, float, str]:
    current_roe = eps / book_value if book_value > 0 else 0.0
    return eps, current_roe, "latest held trailing EPS; newest annual EPS if TTM is unavailable"


def _is_regulated_financial(profile: dict[str, Any]) -> bool:
    words = " ".join(str(profile.get(key) or "") for key in ("sector", "industry")).lower()
    return any(word in words for word in ("bank", "nbfc", "insurance"))


def _payout_ratio(
    profile: dict[str, Any],
    price: float | None,
    eps: float,
    tables: dict[str, Any],
) -> tuple[float, bool, bool]:
    reported = [
        value
        for value in _row(tables.get("profit-loss", {}), ("Dividend Payout %",))[-5:]
        if value is not None and value >= 0
    ]
    if reported:
        observed = statistics.median(reported)
        return min(1.0, observed / 100), False, observed > 100

    dividend_yield = _number(profile.get("dividend_yield"))
    if dividend_yield is None or price is None or eps <= 0:
        return 0.0, True, False
    payout = (dividend_yield / 100 * price) / eps
    return max(0.0, min(1.0, payout)), False, payout > 1.0


def _cost_of_equity(
    beta_result: dict[str, Any], premium_result: dict[str, Any], risk_free: dict[str, Any] | None
) -> dict[str, Any]:
    raw_premia = premium_result["premia"]
    # Damodaran's July 2026 India ERP estimate is applied uniformly; IIMA's
    # market factor remains the beta regressor, while its SMB/HML averages
    # supply the size and value premia.
    market = INDIA_ERP
    size = _number(raw_premia.get("SMB")) or 0.0
    value = _number(raw_premia.get("HML")) or 0.0
    betas = beta_result["betas"]
    if risk_free is not None:
        rf = float(risk_free["rate"])
        rf_source = risk_free["source"]
        rf_as_of = risk_free["as_of"]
        rf_fallback = False
    else:
        monthly = factors.observations("monthly")["rows"]
        recent_rf = [row["RF"] for date, row in sorted(monthly.items())[-12:] if "RF" in row]
        rf = (sum(recent_rf) / len(recent_rf) * 12) if recent_rf else 0.06
        rf_source = "IIMA monthly RF, annualized; fallback"
        rf_as_of = max(monthly, default="")
        rf_fallback = True
    uncapped = rf + betas["MF"] * market + betas["SMB"] * size + betas["HML"] * value
    rate = uncapped
    return {
        "rate": rate,
        "uncapped_rate": uncapped,
        "risk_free_rate": rf,
        "risk_free_source": rf_source,
        "risk_free_as_of": rf_as_of,
        "risk_free_fallback": rf_fallback,
        "premia": {"market": market, "size": size, "value": value},
        "market_erp_as_of": INDIA_ERP_AS_OF,
        "premia_sources": {
            "market": "Damodaran India total ERP, July 1 2026 (6.9202%)",
            "size": "IIMA full-sample monthly SMB arithmetic mean, annualized",
            "value": "IIMA full-sample monthly HML arithmetic mean, annualized",
        },
        "betas": betas,
        "raw_betas": beta_result.get("raw_betas"),
        "beta_observations": beta_result["observations"],
        "beta_fallback": beta_result["fallback"],
        "clamped": False,
        "method": "India ERP plus issuer three-factor beta premia; no issuer-specific rate bounds",
        "factor_release": premium_result["release"],
        "factor_through": premium_result["through"],
        "factor_premium_observations": premium_result["observations"],
        "factor_source": premium_result["source"],
        "factor_sha256": premium_result["sha256"],
        "beta_source": beta_result["source"],
        "beta_sha256": beta_result["sha256"],
    }


def build(
    *,
    symbol: str,
    fundamentals_as_of: str,
    fundamentals_path: str,
    profile: dict[str, Any],
    metrics: dict[str, Any],
    tables: dict[str, Any],
    peers: dict[str, Any],
    price: dict[str, Any],
) -> dict[str, Any]:
    """Build one common equity residual-income value and peer-multiple cross-checks."""
    warnings = [
        "Analyst EPS forecasts are not held; reported trailing EPS anchors the forecast.",
        "Fundamentals availability uses the snapshot date, not original filing time; this is not back-test safe.",
        "Peer P/E and P/B are raw cross-checks; they do not set the primary intrinsic estimate.",
        "India ERP is an annual country-risk estimate, not a live implied premium; its source date is shown with cost-of-equity assumptions.",
        "IIMA republishes revised historical factors; this latest release is not a point-in-time factor vintage.",
        "Unshrunk five-year OLS factor betas are not capped; thin trading and short histories can make them noisy.",
    ]
    price_close = _number(price.get("close")) or _number(profile.get("price"))
    book_value = _number(profile.get("book_value"))
    eps = _number(metrics.get("eps_ttm"))
    if eps is None:
        eps = _number(metrics.get("eps"))
    annual_eps = [v for v in _row(tables.get("profit-loss", {}), ("EPS in Rs",)) if v is not None]
    if eps is None and annual_eps:
        eps = annual_eps[-1]
    total_return_series = price.get("total_return_series") or []
    betas = factors.estimate_betas(total_return_series or price.get("series") or [])
    if not total_return_series:
        warnings.append(
            "Total-return price history is unavailable; cash dividends are omitted from beta estimation."
        )
    else:
        return_factor_through = str(price.get("total_return_factor_through") or "")
        price_day = str(price.get("day") or "")
        if not return_factor_through:
            warnings.append(
                "No dated total-return adjustment factors are held; beta may omit dividends."
            )
        elif price_day and return_factor_through < price_day:
            warnings.append(
                f"Dividend reinvestment factors run through {return_factor_through}; later dividends may be missing from beta returns."
            )
    premia = factors.long_run_premia()
    risk_free = factors.current_risk_free()
    cost = _cost_of_equity(betas, premia, risk_free)
    models: dict[str, float | None] = {
        "residual_income": None,
        "peer_pe": None,
        "peer_pb": None,
    }
    assumptions: dict[str, Any] = {}
    roe_history = _historical_roe(tables)
    recent_roes = [roe for _, roe in roe_history[-5:]]

    if book_value is not None and book_value > 0 and eps is not None:
        eps_1, current_roe, forecast_method = _earnings_anchor(eps, book_value)
        payout, payout_fallback, payout_capped = _payout_ratio(profile, price_close, eps_1, tables)
        if recent_roes:
            base_roe = statistics.median(recent_roes)
            low_roe = _quantile(recent_roes, 0.25) if len(recent_roes) >= 4 else None
            high_roe = _quantile(recent_roes, 0.75) if len(recent_roes) >= 4 else None
            roe_source = f"median of {len(recent_roes)} held annual ROEs"
        else:
            base_roe = current_roe
            low_roe = high_roe = None
            roe_source = "current trailing ROE proxy; company history unavailable"

        cases = {
            "base": _multistage_residual_income(
                book_value,
                current_roe,
                base_roe,
                payout,
                cost["rate"],
                risk_free=cost["risk_free_rate"],
            )
        }
        if low_roe is not None and high_roe is not None:
            cases["low"] = _multistage_residual_income(
                book_value,
                current_roe,
                low_roe,
                payout,
                cost["rate"],
                risk_free=cost["risk_free_rate"],
            )
            if high_roe > cost["rate"]:
                cases["high"] = _multistage_residual_income(
                    book_value,
                    current_roe,
                    high_roe,
                    payout,
                    cost["rate"],
                    years=ROE_ANCHOR_YEARS,
                    risk_free=cost["risk_free_rate"],
                    terminal_mode="persistent_excess_returns",
                )
            else:
                cases["high"] = _multistage_residual_income(
                    book_value,
                    current_roe,
                    high_roe,
                    payout,
                    cost["rate"],
                    risk_free=cost["risk_free_rate"],
                )
        models["residual_income"] = cases["base"]["value"]
        if "low" in cases and "high" in cases:
            models["residual_income_low"] = cases["low"]["value"]
            models["residual_income_high"] = cases["high"]["value"]
        assumptions = {
            "book_value_per_share": book_value,
            "reported_eps_per_share": eps_1,
            "current_roe": current_roe,
            "historical_roe": [{"period": period, "roe": roe} for period, roe in roe_history[-5:]],
            "terminal_roe_source": roe_source,
            "payout_ratio": payout,
            "payout_assumed": payout_fallback,
            "forecast_method": (
                f"{EXPLICIT_YEARS}-year fade: current ROE proxy to a data-derived year-5 anchor, "
                f"then to cost of equity by year {EXPLICIT_YEARS}; {forecast_method}"
            ),
            "forecast_roe": {
                "year_1": cases["base"]["year_1_roe"],
                "year_2": current_roe + (base_roe - current_roe) * 2 / ROE_ANCHOR_YEARS,
                "year_3": current_roe + (base_roe - current_roe) * 3 / ROE_ANCHOR_YEARS,
                "year_5": cases["base"]["year_5_roe"],
                "year_10": cases["base"]["year_10_roe"],
            },
            "forecast_eps": {
                "year_1": cases["base"]["year_1_eps"],
                "year_5": cases["base"]["year_5_eps"],
                "year_10": cases["base"]["year_10_eps"],
            },
            "valuation_scenarios": cases,
            "sector_model": "common_residual_income",
        }
        if payout_fallback:
            warnings.append(
                "Dividend payout could not be inferred; the model assumes full earnings retention."
            )
        if payout_capped:
            warnings.append(
                "Observed dividend payout exceeded earnings; payout was limited to 100% for sustainable book-value growth."
            )
        if len(recent_roes) < 4:
            warnings.append(
                "Fewer than four annual ROEs are held; the model uses available history or trailing ROE as its year-5 anchor and does not show an ROE scenario band."
            )
        elif high_roe is not None and high_roe > cost["rate"]:
            warnings.append(
                "The upper scenario assumes the 75th-percentile historical ROE persists after year five; treat it as an optimistic persistence case, not a probability forecast."
            )
        if abs(current_roe) > 1:
            warnings.append(
                "TTM EPS divided by ending book value implies ROE above 100%; verify one-off earnings, share count, and book-value basis."
            )
        sensitivity: dict[str, float] = {}
        for label, rate in (
            ("minus_1pp", cost["rate"] - 0.01),
            ("base", cost["rate"]),
            ("plus_1pp", cost["rate"] + 0.01),
        ):
            sensitivity[label] = _multistage_residual_income(
                book_value,
                current_roe,
                base_roe,
                payout,
                rate,
                risk_free=cost["risk_free_rate"],
            )["value"]
        assumptions["sensitivity"] = sensitivity
    elif book_value is None or book_value <= 0:
        warnings.append(
            "Residual-income value unavailable because positive book value per share is missing."
        )
    else:
        warnings.append("Residual-income value unavailable because reported EPS is not held.")

    median_pe = _number(peers.get("valuation_median_pe"))
    if median_pe and median_pe > 0 and eps is not None and eps > 0:
        models["peer_pe"] = median_pe * eps
    median_pb = _number(peers.get("valuation_median_pb"))
    if median_pb and median_pb > 0 and book_value is not None and book_value > 0:
        models["peer_pb"] = median_pb * book_value
    if any(models.get(key) is not None for key in ("peer_pe", "peer_pb")):
        warnings.append(
            "Peer cross-checks use the held company digest, whose constituent fundamentals may be older than this valuation snapshot."
        )
    if profile.get("consolidated") is False:
        warnings.append(
            "The held statements are standalone; subsidiaries are not included in this per-share estimate."
        )
    elif profile.get("consolidated") is None:
        warnings.append("The held statement consolidation basis is not identified.")

    # Residual income is the primary intrinsic model. Peer multiples remain
    # visible cross-checks; market-derived multiples are not blended into the
    # headline as if they were independent intrinsic estimates.
    composite = models["residual_income"]
    if composite is not None and (composite <= 0 or cost["rate"] <= 0):
        composite = None
        warnings.append(
            "Residual-income value is unavailable because the model produced a non-positive equity value or non-positive cost of equity. Peer multiples remain cross-checks only."
        )
    has_scenario_range = False
    if composite is None:
        status = "unavailable"
        upside = None
        model_range = None
        unavailable_reason = (
            "No supported valuation model produced a positive value from held inputs."
        )
        warnings.append(unavailable_reason)
    else:
        status = "available"
        upside = composite / price_close - 1 if price_close and price_close > 0 else None
        residual_income = models.get("residual_income")
        candidates = (
            [models.get("residual_income_low"), models.get("residual_income_high")]
            if residual_income is not None and residual_income > 0
            else []
        )
        scenario_values = [value for value in candidates if value is not None and value > 0]
        has_scenario_range = len(scenario_values) == 2
        model_range = (
            {"low": min(scenario_values), "high": max(scenario_values)}
            if has_scenario_range
            else None
        )
        unavailable_reason = ""
    if cost["beta_fallback"]:
        warnings.append(
            "Factor betas fell back to neutral priors because price/factor overlap was too short."
        )
    if cost["risk_free_fallback"]:
        warnings.append(
            "Current India 10-year yield was unavailable; the model used the IIMA RF fallback."
        )
    if _is_regulated_financial(profile) and models.get("residual_income") is not None:
        warnings.append(
            "The common equity model does not explicitly forecast regulatory capital ratios, solvency requirements, or risk-weighted assets."
        )
    industry_levels = profile.get("sector_levels") or []
    industry_text = " ".join(
        [str(profile.get("industry") or ""), *(str(value) for value in industry_levels)]
    ).lower()
    if any(term in industry_text for term in ("realty", "real estate", "property development")):
        warnings.append(
            "For real-estate developers, the held statements do not include project-level presales, completion schedules, or a land-bank NAV; the common ROE model may miss their main value drivers."
        )
    if any(
        term in industry_text for term in ("metals & mining", "iron & steel", "oil & gas", "energy")
    ):
        warnings.append(
            "The five-year ROE history may not span a full commodity cycle; no forward commodity curve, capacity, or normalized-margin forecast is held."
        )
    if any(term in industry_text for term in ("software", "it - software")):
        warnings.append(
            "Reported book equity excludes much internally generated software value; no R&D capitalization or analyst growth forecast is held."
        )
    if cost["rate"] <= 0:
        warnings.append(
            "Estimated cost of equity is non-positive; no discounted fair value is reported."
        )
    if cost["factor_through"] < str(price.get("day") or "")[:7]:
        warnings.append(f"IIMA factors are stale after {cost['factor_through']}.")
    range_type = "roe_persistence_scenarios" if has_scenario_range else "none"
    if (
        model_range
        and model_range["low"] > 0
        and model_range["high"] / model_range["low"] - 1 > 0.30
    ):
        warnings.append(
            "The lower and upper ROE-persistence cases differ by more than 30%; the scenario range is wide."
        )

    return {
        "model_version": MODEL_VERSION,
        "status": status,
        "reason": unavailable_reason,
        "symbol": symbol,
        "fundamentals_as_of": fundamentals_as_of,
        "fundamentals_path": fundamentals_path,
        "price_as_of": str(price.get("day") or ""),
        "current_price": price_close,
        "fair_value_per_share": composite,
        "upside": upside,
        "range_type": range_type,
        "valuation_method": "Common residual-income engine; central and lower cases fade to cost of equity by year ten, with an upper ROE-persistence case.",
        "confidence": "low",
        "confidence_reason": (
            "No analyst forecasts are held. The central case fades excess ROE to cost of equity by year ten; "
            "the scenario range is a persistence sensitivity, not a probability or confidence interval."
        ),
        "sector_model": "common_residual_income",
        "models": {**models, "composite": composite},
        "model_range": model_range,
        "cost_of_equity": cost,
        "assumptions": assumptions,
        "warnings": warnings,
        "inputs": {
            "book_value_per_share": book_value,
            "eps_per_share": eps,
            "price_per_share": price_close,
            "peer_median_pe": median_pe,
            "peer_median_pb": median_pb,
            "peer_median_roe": _number(peers.get("median_roe")),
            "sector": profile.get("sector") or "",
            "industry": peers.get("industry") or profile.get("industry") or "",
        },
    }


def save_snapshot(result: dict[str, Any]) -> str:
    """Persist each distinct input/output combination as an immutable JSON run."""
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
    run_id = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    target = SNAPSHOTS / str(result["symbol"]) / f"{run_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        payload = {**result, "run_id": run_id, "stored_at": datetime.now(UTC).isoformat()}
        temporary = target.with_suffix(".partial")
        temporary.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        temporary.replace(target)
        target.chmod(0o444)
    return run_id
