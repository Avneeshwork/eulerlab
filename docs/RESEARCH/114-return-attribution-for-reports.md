# 114 — Where a backtest's return came from

**Question (operator, 2026-10-18).** For any backtest or paper deployment,
show whether the return came from particular holdings, sectors, years, or
simply from being long a rising market.

## Methods considered

| Method | Needs | Here |
|---|---|---|
| Brinson attribution (allocation, selection, interaction by sector) | A benchmark's sector weights and returns each period | Not held: no point-in-time Nifty sector weights. Not built |
| Contribution analysis (each holding's rupee profit, summed by group) | The fills and the final marks | Held: `reports.Constituent.contribution`, which reconciles to the equity change |
| Returns-based regression on the market (CAPM) | The strategy's daily returns and an index | Held: the equity curve and the Nifty 50 closes (`market_history`) |
| Factor regression (size, value, momentum) | Point-in-time Indian factor returns | Not held (the reason research 113's residual models use the market alone) |

Sources: Brinson, Hood & Beebower (1986), *Determinants of Portfolio
Performance*, FAJ 42(4), and Sharpe (1992), *Asset Allocation: Management
Style and Performance Measurement*, JPM 18(2), for the two standard families.
Neither was fetched this session; both are cited from memory as the standard
references, and nothing here depends on a detail of either.

## Decision

`src/eulerlab/attribution.py`, computed when a report is read, so every stored
backtest and every deployment gets it without a re-run:

- **Holdings:** share of net profit from the best 1, 5 and 10; names needed for
  half and four-fifths of it; the return (total and a year) with the best 1 and
  the best 5 removed. Removing the best names is the luck test: a rule whose
  return vanishes without five stocks has found five stocks.
- **Sectors and industries:** contribution summed by NSE's classification as it
  stands today (A-061); companies missing from today's digest are "Unclassified".
- **Years:** each year's return from the equity curve; closed trades' net
  profit by exit year with open positions in the final year; each year's
  largest contributor and its share.
- **Market:** daily returns on the Nifty 50 — beta, correlation, R², the mean
  return beta alone would have earned, and annual alpha.

Shown in a new Attribution tab on the report page (backtests and deployments).

## First reading (Weinstein Stage 2, research 113)

Top 5 holdings: 52% of profit; CUPID alone 24%. Without the best 5 it still
earns 21.3% a year (Nifty 11.5%), so the edge is broad, not five stocks.
Beta 1.13, R² 0.37: the market explains about 13.5 of its 30.5 points a year;
alpha about 17% a year.

## Confidence and open questions

High for the arithmetic (it reconciles to the paisa; `tests/test_attribution.py`).
Open: sector labels are today's (A-061), and 17% of Weinstein's profit is
unclassified (delisted or renamed companies); a real Brinson split and factor
attribution need point-in-time sector weights and Indian factor returns,
neither held.
