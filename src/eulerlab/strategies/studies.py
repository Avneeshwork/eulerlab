"""Research papers that were coded as studies, listed for the strategy library.

Operator, 2026-10-12: "get all papers in research and update in strategy
library". Nine rules had been coded from papers and run (research 070, 071,
076) and could be found only by reading `docs/RESEARCH/`: the library listed
none of them.

Each is a calculation with its own make target, not a `Strategy` and not one
of the minute-bar scanner's signals, so the library cannot run it from a
button. It can show it: the source, what the source reported, the steps as
coded, and every published setting's result, which `research/library_sync.py`
copies from the study's output file into the result store.

Plain data, not `Declaration` objects: `strategies/__init__.py` builds those,
and importing it from here would be a circle.

`configurations` maps a label to the study's own name for that run. The
**last** one is the source's main setting and becomes the library's headline,
because the library shows the most recent run and they are written in order.
"""

from __future__ import annotations

from typing import Any

SESSION = "intraday_papers"
INDIA = "india_intraday_papers"
OPTIONS = "options_strategies"

COMMANDS = {
    SESSION: "make intraday-papers",
    INDIA: "make india-intraday",
    OPTIONS: "make options-strategies",
}

FIRST_PRINT = (
    "The first minute's print is never used: a range, a signal and a fill all start "
    "at 09:16 (research 075)."
)
ETF_COSTS = (
    "NSE intraday charges from the cost router plus 1 bp of slippage a side (A-052): "
    "about 6 bps a round trip in NIFTYBEES."
)

ENTRIES: tuple[dict[str, Any], ...] = (
    # --- research 071 -------------------------------------------------------------
    {
        "id": "gao_last_half_hour",
        "title": "First half-hour predicts the last half-hour (Nifty ETF)",
        "summary": "Trade 15:00 to the close in the direction of the day's first half-hour.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Gao, Han, Li & Zhou (2018), Journal of Financial Economics; "
        "working paper of December 2015 read",
        "published": "S&P 500 ETF, 1993-2013: 6.67% a year, Sharpe 1.08, 54% of days right, "
        "trading the last half-hour on the first half-hour's sign.",
        "paper_url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2440866",
        "tested_on": "SPY, half-hour returns, 1993 to 2013",
        "research": "docs/RESEARCH/071-two-intraday-papers-on-niftybees.md",
        "study": SESSION,
        "instrument": "NIFTYBEES",
        "logic": [
            "r1 is the return from the previous official close to 09:45, so it includes "
            "the overnight gap. r12 is 14:30 to 15:00.",
            "At 15:00 go long if the signal is positive and short if it is negative; with "
            "both signals, trade only when they agree.",
            "Close at 15:24, a minute before the broker squares off (the paper holds to "
            "the close, which a short cannot do).",
            ETF_COSTS,
        ],
        "configurations": {
            "last half-hour on r12, exit 15:24": "last half-hour on r12, tradable exit",
            "last half-hour on both, exit 15:24": "last half-hour on both, tradable exit",
            "last half-hour on r1, exit 15:24": "last half-hour on r1, tradable exit",
        },
    },
    {
        "id": "noise_area_momentum",
        "title": "Leaving the noise area (Nifty ETF)",
        "summary": "Follow the Nifty ETF when it moves further from its open than it "
        "usually has by that minute.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Zarattini, Aziz & Barbon (2025), Swiss Finance Institute paper 24-97",
        "published": "SPY, 2007 to early 2024, after their costs: Sharpe 1.24 and 9.7% a "
        "year at 1x with a band-or-VWAP stop; 0.61 with the opposite band as the stop.",
        "paper_url": "https://alexandria.unisg.ch/server/api/core/bitstreams/"
        "a99aba00-f967-49b3-aceb-f544dc386e0b/content",
        "tested_on": "SPY, one-minute bars, May 2007 to early 2024",
        "research": "docs/RESEARCH/071-two-intraday-papers-on-niftybees.md",
        "study": SESSION,
        "instrument": "NIFTYBEES",
        "logic": [
            "The band at each minute is the open (or the previous close, whichever is "
            "further out) plus and minus the average move by that minute over 14 days.",
            "Every 30 minutes from the open: long above the band, short below it.",
            "Stop at the opposite band, or at the nearer of the band and the session "
            "VWAP. Flat by 15:24.",
            "The open is the first minute's close, not the 09:15 print (research 071).",
            ETF_COSTS,
        ],
        "configurations": {
            "opposite-band stop, exit 15:24": "noise area, opposite-band stop, tradable exit",
            "band or VWAP stop, exit 15:24": "noise area, band+VWAP stop, tradable exit",
        },
    },
    # --- research 070 -------------------------------------------------------------
    {
        "id": "nifty_short_strangle",
        "title": "Monthly short strangle on the Nifty",
        "summary": "After each monthly expiry sell an out-of-the-money call and put and "
        "hold them to expiry.",
        "kind": "quant",
        "shape": "structure",
        "asset_class": "options",
        "timeframe": "1d",
        "source": "[paper] Bangur (2020), Journal of Investment Strategies",
        "published": "Nifty, 2007-2019, monthly: the short strangle beat the long one at "
        "every strike distance. Abstract only; the paper is paywalled.",
        "paper_url": "https://www.risk.net/journal-of-investment-strategies/7721271/"
        "strangle-to-resuscitate-evidence-from-india",
        "tested_on": "Nifty index options, monthly, 2007 to 2019",
        "research": "docs/RESEARCH/070-two-indian-options-strategies.md",
        "study": OPTIONS,
        "instrument": "Nifty options",
        "logic": [
            "On the first session after a monthly expiry, sell the call and the put "
            "2%, 4% or 6% out of the money (A-049).",
            "Hold to expiry and settle at intrinsic value against the Nifty close.",
            "Return is on a margin of 15% of notional (A-050). Costs from the options "
            "cost model; continuous units, not lots (S-039).",
        ],
        "configurations": {
            "strikes 6% out": "short_strangle_leg3",
            "strikes 4% out": "short_strangle_leg2",
            "strikes 2% out": "short_strangle_leg1",
        },
    },
    {
        "id": "nifty_covered_call",
        "title": "Covered call on the Nifty, 5% in the money",
        "summary": "Hold the Nifty future and sell the same-month call nearest 5% in the money.",
        "kind": "quant",
        "shape": "structure",
        "asset_class": "options",
        "timeframe": "1d",
        "source": "[paper] Aggarwal (2011), Asia-Pacific Business Review",
        "published": "S&P CNX Nifty, October 2005 to September 2010: covered calls on "
        "in-the-money strikes did best. From a search summary; the paper was not opened.",
        "paper_url": "",
        "tested_on": "S&P CNX Nifty and its calls, October 2005 to September 2010",
        "research": "docs/RESEARCH/070-two-indian-options-strategies.md",
        "study": OPTIONS,
        "instrument": "Nifty future and call",
        "logic": [
            "Buy the near-month Nifty future and sell the same-month call nearest 5% "
            "in the money, at the close.",
            "Daily: close both at the next close, as the paper does. Monthly: open "
            "after each expiry and hold to expiry.",
            "Return is on full notional. Costs from the options cost model.",
        ],
        "configurations": {
            "held a month": "covered_call_monthly_5itm",
            "held a day": "covered_call_daily_5itm",
        },
    },
    # --- research 076 -------------------------------------------------------------
    {
        "id": "late_opening_range",
        "title": "Breakout of the first one or two hours (Nifty ETF)",
        "summary": "Follow the first 3-minute close outside the range of the first one "
        "or two hours, with the stop at the other side.",
        "kind": "technical",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[practitioner] Rao (2026), Zerodha In The Money, "
        "All About Opening Range Breakout, Part 1",
        "published": "Nifty index, 3-minute candles, January 2019 to February 2026, no "
        "costs: the 09:15-11:15 range does best and 09:15-10:15 second; longs win about "
        "60% of the time, shorts about 50%. Charts only, no table.",
        "paper_url": "https://inthemoneybyzerodha.substack.com/p/all-about-opening-range-breakout",
        "tested_on": "Nifty 50 index, 3-minute candles, January 2019 to February 2026",
        "research": "docs/RESEARCH/076-five-indian-intraday-rules.md",
        "study": INDIA,
        "instrument": "NIFTYBEES",
        "logic": [
            "The range is the high and low from 09:16 to 10:15, or to 11:15. " + FIRST_PRINT,
            "After the range, the first 3-minute candle to close above it is bought and "
            "the first to close below it is sold short, at the next minute's open. One "
            "trade a day.",
            "The stop is the other side of the range. The article gives no target and "
            "no exit time, so an open position is closed at 15:24.",
            ETF_COSTS,
        ],
        "configurations": {
            "range to 10:15": "range 09:15-10:15, 3-minute close, stop at the range",
            "range to 11:15": "range 09:15-11:15, 3-minute close, stop at the range",
        },
    },
    {
        "id": "orb_thirty_two_r",
        "title": "30-minute opening range, target twice the risk (Nifty ETF)",
        "summary": "Enter on the break of the 09:15-09:45 range; stop at the other "
        "side, target at twice the range, out at 14:30.",
        "kind": "technical",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[practitioner] Doraigari (2026), IntradayLab, "
        "Best Intraday Breakout Strategy for Nifty 50",
        "published": "Nifty 50 index, 15-minute candles, July 2017 to March 2026, no "
        "costs: 2,122 trades, +91.6%, win rate 48.7%, profit factor 1.23, worst fall "
        "11.2%, Sharpe 1.16. The article's own win count (887) does not match its win rate.",
        "paper_url": "https://intradaylab.com/blog/nifty-orb-breakout-strategy-backtest",
        "tested_on": "Nifty 50 index (spot), 15-minute candles, July 2017 to March 2026",
        "research": "docs/RESEARCH/076-five-indian-intraday-rules.md",
        "study": INDIA,
        "instrument": "NIFTYBEES",
        "logic": [
            "The range is the high and low from 09:16 to 09:44. " + FIRST_PRINT,
            "A stop order rests at each edge. The first one touched is the trade; a "
            "minute that touches both is no trade. One trade a day.",
            "Stop at the other edge. Target at twice the range from the entry. A "
            "minute that spans both is counted as the stop.",
            "Whatever is still open is closed at 14:30.",
            ETF_COSTS,
        ],
        "configurations": {
            "as published": "range 09:15-09:45, stop at the range, 2R target, out 14:30",
        },
    },
    {
        "id": "orb_volume_surge",
        "title": "Opening range breakout with a volume surge (large stocks)",
        "summary": "In each stock, follow a close outside the opening range only when "
        "that bar's volume is well above usual, and hold a few bars.",
        "kind": "technical",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Wang & Gangwar (2025), SSRN 5198458",
        "published": "Tata Motors, about one year: every variant returned more than "
        "buying at the open and selling at the close, but bootstrap p-values were 0.45 "
        "to 0.50, so the authors could not tell the edge from luck. Abstract only.",
        "paper_url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5198458",
        "tested_on": "Tata Motors on the NSE, intraday prices, about one year",
        "research": "docs/RESEARCH/076-five-indian-intraday-rules.md",
        "study": INDIA,
        "instrument": "100 largest stocks",
        "logic": [
            "Bars of 5, 15 or 30 minutes. The range is the first bar from 09:16. " + FIRST_PRINT,
            "A later bar that closes above the range is bought, and one that closes "
            "below is sold short, only if its volume is at least 1.2 or 1.5 times that "
            "bar's average over the last 20 sessions (A-058: the abstract gives the "
            "thresholds, not what they are measured against).",
            "Enter at the next bar's open and leave 2, 3 or 5 bars later, or at 15:10. "
            "One trade a stock a day.",
            "All 18 published settings are run. Equity is split equally across the "
            "stocks; charges from the cost router plus 2 bps of slippage a side (A-056).",
        ],
        "configurations": {
            f"{size}-minute range, volume {surge}x, hold {hold} bars": (
                f"{size}-minute range, volume {surge}x, hold {hold} bars"
            )
            for size in (5, 30, 15)
            for surge in (1.2, 1.5)
            for hold in (2, 5, 3)
        },
    },
    {
        "id": "rest_of_day_momentum",
        "title": "The day so far decides the last half-hour (Nifty ETF)",
        "summary": "Trade 15:00 to the close in the direction of the move since yesterday's close.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Hedging Demand and Intraday Momentum within the Indian Stock "
        "Market (2024), after Baltussen, Da, Lammers & Martens (2021)",
        "published": "Baltussen et al., 60 futures, 1974-2020: the return up to the last "
        "half-hour predicts the last half-hour everywhere. The Indian paper says parts "
        "carry over to Nifty futures; its text could not be fetched and its numbers "
        "are not known.",
        "paper_url": "https://www.researchgate.net/publication/383567351",
        "tested_on": "Nifty 50 futures, intraday (Indian paper); 60 futures worldwide (design)",
        "research": "docs/RESEARCH/076-five-indian-intraday-rules.md",
        "study": INDIA,
        "instrument": "NIFTYBEES",
        "logic": [
            "At 15:00 measure the return from the previous official close to the 14:59 "
            "close. It includes the overnight gap.",
            "Go long if it is positive and short if it is negative, at the 15:00 open.",
            "Close at 15:24. The Indian paper's second signal, net gamma exposure, "
            "needs option open interest by strike and is not coded.",
            ETF_COSTS,
        ],
        "configurations": {"as published": "previous close to 15:00 decides 15:00-15:24"},
    },
    {
        "id": "extreme_move_fade",
        "title": "Fade the day's most extreme half-hour moves (large stocks)",
        "summary": "At the open and at 12:15, buy the three stocks that fell most in "
        "the last half-hour and sell short the three that rose most.",
        "kind": "quant",
        "shape": "cross-section",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Tripathi & Aggarwal (2015), International Journal of Financial "
        "Management 5(1)",
        "published": "CNX 500 stocks, 2010, 30-minute returns, no costs: extreme moves "
        "reverse. Falls correct within 30 minutes; rises take a few hours. The fade "
        "pays more at the open than at midday. The authors warn costs may remove it.",
        "paper_url": "https://www.publishingindia.com/storage/PDFBrochures/2481.pdf",
        "tested_on": "S&P CNX 500 stocks, 30-minute returns, January to December 2010",
        "research": "docs/RESEARCH/076-five-indian-intraday-rules.md",
        "study": INDIA,
        "instrument": "100 largest stocks",
        "logic": [
            "At the open the move is yesterday's 15:14 close to today's first-minute "
            "close; at midday it is 11:45 to 12:15. Stocks at Rs 10 or less are left out.",
            "Buy the three with the lowest move and sell short the three with the "
            "highest, at the next minute's open. The paper ranks by return less the "
            "Nifty's, which gives the same order.",
            "Close after 30 minutes or after 150 minutes.",
            "Six equal slots; charges from the cost router plus 2 bps of slippage a side (A-056).",
        ],
        "configurations": {
            f"at {event}, hold {minutes} minutes": (
                f"fade 3 up and 3 down at the {event}, hold {minutes} minutes"
            )
            for event, minutes in (("midday", 30), ("midday", 150), ("open", 150), ("open", 30))
        },
    },
)

IDS = frozenset(entry["id"] for entry in ENTRIES)
