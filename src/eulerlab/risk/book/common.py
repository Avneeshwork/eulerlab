"""The windows, thresholds and market the risk figures are read with."""

from __future__ import annotations

WINDOW = 250
"""Trading days of history the book is run through: about a year."""

# ASSUMPTION: A-059 — the weight on yesterday in the recent-weighted spread.
LAMBDA = 0.94
"""RiskMetrics' daily decay. Not fitted to anything here."""

Z = {0.95: 1.6448536269514722, 0.99: 2.3263478740408408}
TRADING_DAYS = 252
MIN_DAYS = 60
"""Fewer past days than this and no risk figure is given: a VaR from a few
weeks is a guess with a rupee sign."""
MIN_GAP_NIGHTS = 30
"""Signal nights in the window before a "when it holds" VaR is given."""
MIN_BAND_DAYS = 20
"""Days live before a deployment is judged against its backtest."""
MARKET = "NIFTYBEES"
"""The Nifty 50 ETF, which is in the price panel. Betas are measured to it."""
