"""Research papers that were coded as studies, listed for the strategy library.

Operator, 2026-10-12: "get all papers in research and update in strategy
library". Nine rules had been coded from papers and run (research 070, 071,
076) and could be found only by reading `docs/RESEARCH/`: the library listed
none of them. Research 078 added two more on 2026-10-13.

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
STOCKS = "stock_intraday_papers"
GOLD_STOCK_SCREEN = "gold_stock_intraday_screen"
MCX_GOLD_BACKTEST = "mcx_gold_backtest"
STOCK_CANDIDATES = "stock_intraday_candidates"
COMPANY_GITHUB = "company_github_stock_strategies"
GITHUB_FOLLOWUP = "github_followup_stock_strategies"
GITHUB_MOMENTUM_PULLBACK = "github_momentum_pullback_stock_strategies"
INSIDE_BAR = "inside_bar_stock_strategies"
HIKKAKE = "hikkake_stock_strategies"
GITHUB_EMA = "github_ema_crossover_stock_strategies"
SUPERTREND_MTF = "supertrend_alignment_stock_strategies"
FII_PARTICIPANT_OI = "fii_participant_oi_stock_strategies"
COST_AWARE_ML = "cost_aware_ml_nse_stock_strategies"
GITHUB_KELTNER = "github_keltner_stock_strategies"
GITHUB_DONCHIAN = "github_donchian_stock_strategies"
GITHUB_PIVOT = "github_pivot_stock_strategies"
GITHUB_ENGULFING = "github_engulfing_stock_strategies"
GITHUB_MOMENTUM_BURST = "github_momentum_burst_stock_strategies"
GITHUB_RSI2 = "github_rsi2_pullback_stock_strategies"

COMMANDS = {
    SESSION: "make intraday-papers",
    INDIA: "make india-intraday",
    OPTIONS: "make options-strategies",
    STOCKS: "make stock-intraday",
    GOLD_STOCK_SCREEN: "make gold-stock-intraday-screen",
    MCX_GOLD_BACKTEST: "make mcx-gold-backtest",
    STOCK_CANDIDATES: "make stock-intraday-candidates",
    COMPANY_GITHUB: "make company-github-intraday",
    GITHUB_FOLLOWUP: "make github-followup-intraday",
    GITHUB_MOMENTUM_PULLBACK: "make github-momentum-pullback-intraday",
    INSIDE_BAR: "make inside-bar-intraday",
    HIKKAKE: "make hikkake-intraday",
    GITHUB_EMA: "make github-ema-crossover-intraday",
    SUPERTREND_MTF: "make supertrend-alignment-intraday",
    FII_PARTICIPANT_OI: "make fii-positioning-intraday",
    COST_AWARE_ML: "make cost-aware-ml-intraday",
    GITHUB_KELTNER: "make github-keltner-intraday",
    GITHUB_DONCHIAN: "make github-donchian-intraday",
    GITHUB_PIVOT: "make github-pivot-intraday",
    GITHUB_ENGULFING: "make github-engulfing-intraday",
    GITHUB_MOMENTUM_BURST: "make github-momentum-burst-intraday",
    GITHUB_RSI2: "make github-rsi2-intraday",
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
    # --- research 078 -------------------------------------------------------------
    {
        "id": "end_of_day_reversal",
        "title": "The day's losers rise into the close (large stocks)",
        "summary": "From 14:40 to 15:10 hold the stocks that have fallen most since "
        "yesterday's close, against those that have risen most.",
        "kind": "quant",
        "shape": "cross-section",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Baltussen, Da & Soebhag (2025), End-of-Day Reversal, working paper",
        "published": "US stocks from 1993, last half-hour, before costs: losers beat winners "
        "by 3.78 bps a day value-weighted (t 10.7) and 6.38 equal-weighted (t 17.3); 3.41 "
        "among the largest fifth of firms. The authors say it may not survive costs.",
        "paper_url": "https://academicweb.nd.edu/~zda/EOD.pdf",
        "tested_on": "NYSE, AMEX and NASDAQ stocks, intraday, from 1993",
        "research": "docs/RESEARCH/078-two-us-stock-rules-on-indian-stocks.md",
        "study": STOCKS,
        "instrument": "100 largest stocks",
        "logic": [
            "At 14:10 rank the stocks by their return since the previous session's last "
            "trade. A move of more than 20% is a split or a bad print and is not ranked.",
            "Skip half an hour, as the paper does. At 14:40 buy the lowest fifth (or "
            "tenth) and sell short the highest, at the next minute's open.",
            "Close at 15:10: a stock with derivatives is squared off at 15:12 (A-057). "
            "The paper holds the last half-hour to the close.",
            "Equal slots, half the equity on each side; charges from the cost router "
            "plus 2 bps of slippage a side (A-056).",
        ],
        "configurations": {
            "tenths, losers only": "end-of-day reversal, deciles, losers only, 14:40-15:10",
            "tenths, losers against winners": (
                "end-of-day reversal, deciles, losers against winners, 14:40-15:10"
            ),
            "fifths, losers only": "end-of-day reversal, quintiles, losers only, 14:40-15:10",
            "fifths, losers against winners": (
                "end-of-day reversal, quintiles, losers against winners, 14:40-15:10"
            ),
        },
    },
    {
        "id": "opening_half_hour_repeats",
        "title": "Yesterday's opening half-hour repeats today (large stocks)",
        "summary": "From 09:16 to 09:45 hold the stocks that rose most in yesterday's "
        "opening half-hour, against those that fell most.",
        "kind": "quant",
        "shape": "cross-section",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Heston, Korajczyk & Sadka (2010), Journal of Finance 65(4)",
        "published": "NYSE stocks, 2001-2005, before costs: the top tenth beats the bottom "
        "tenth by about 3 bps in the same half-hour of the next day, and by more than 11 "
        "in the opening half-hour. Bought at the offer and sold at the bid it loses at "
        "every size and time of day.",
        "paper_url": "https://arxiv.org/abs/1005.3535",
        "tested_on": "NYSE stocks, half-hour returns, January 2001 to December 2005",
        "research": "docs/RESEARCH/078-two-us-stock-rules-on-indian-stocks.md",
        "study": STOCKS,
        "instrument": "100 largest stocks",
        "logic": [
            "Rank the stocks by yesterday's return from the 09:16 open to the 09:44 "
            "close. " + FIRST_PRINT,
            "At 09:16 buy the highest tenth and sell short the lowest, at that minute's "
            "open. Close at 09:45.",
            "Only the opening half-hour is run: the paper's largest effect. The other "
            "twelve half-hours are not, and running them would be a search.",
            "Equal slots, half the equity on each side; charges from the cost router "
            "plus 2 bps of slippage a side (A-056).",
        ],
        "configurations": {"as published": "opening half-hour repeats, deciles, 09:16-09:45"},
    },
    {
        "id": "gold_intraday_ma_rules",
        "title": "Five-minute moving averages on Gold ETF",
        "summary": "Follow the sign of the Gold ETF price relative to a published long moving average.",
        "kind": "technical",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Batten, Ciner & Lucey (2018), Does intraday technical analysis have value in precious metal markets?",
        "published": "The paper tests SMA, EMA and WMA rules on five-minute gold and silver data and warns that broad parameter searches create data-mining risk.",
        "paper_url": "https://c.mql5.com/forextsd/forum/174/does_technical_analysis_beat_the_market__evidence_from_high_frequency_trading_in_gold_and_silver.pdf",
        "tested_on": "GOLDBEES, five-minute bars, 2021-08 to 2024-11; 2024 evaluation",
        "research": "docs/RESEARCH/084-gold-and-indian-stock-intraday-screen.md",
        "study": GOLD_STOCK_SCREEN,
        "instrument": "GOLDBEES Gold ETF proxy (not MCX futures)",
        "logic": [
            "At each completed five-minute bar, compare its close with the source-fixed 50, 100, 150 or 200 bar SMA, EMA or WMA.",
            "At the next five-minute bar open, hold long above the average and short below it. Flatten at the session close.",
            "The 1/50 through 1/200 settings are fixed from the source's popular parameterizations; no settings were optimized on the evaluation window.",
            "NSE ETF charges plus 1 bp of slippage per side. This is a Gold ETF proxy, not MCX Gold futures.",
        ],
        "configurations": {
            f"{method.upper()} 1/{slow}": f"{method.upper()}(1) vs {method.upper()}({slow}), 5m, intraday flat"
            for method in ("sma", "ema", "wma")
            for slow in (50, 100, 150, 200)
        },
    },
    {
        "id": "mcx_gold_intraday_ma_filter",
        "title": "SMA(50) with a dead band on MCX Gold futures",
        "summary": "Trade the standard MCX Gold future only when its five-minute close clears a 20 bp band around SMA(50).",
        "kind": "technical",
        "shape": "event",
        "asset_class": "futures",
        "timeframe": "1m",
        "source": "[paper] Batten, Ciner & Lucey (2018), Does intraday technical analysis have value in precious metal markets?",
        "published": "The paper tests five-minute SMA, EMA and WMA rules on precious metals and warns about data snooping.",
        "paper_url": "https://c.mql5.com/forextsd/forum/174/does_technical_analysis_beat_the_market__evidence_from_high_frequency_trading_in_gold_and_silver.pdf",
        "tested_on": "GOLD26DECFUT, 2026-05-14 to 2026-10-14; 78 sufficiently covered MCX sessions",
        "research": "docs/RESEARCH/086-mcx-gold-futures-minute-backtest.md",
        "study": MCX_GOLD_BACKTEST,
        "instrument": "MCX standard Gold futures, one 1 kg lot",
        "logic": [
            "Use the fixed SMA(50) and 20 bp dead band selected earlier on the Gold ETF development sample; do not retune on MCX.",
            "At each completed five-minute bar, enter/reverse at the next five-minute open only when close is at least 20 bp above/below the SMA; hold through the band and flatten at the session end.",
            "Use one standard 1 kg lot, quote multiplier 100 (MCX quotes per 10 g), published commodity futures charges, and 2 bp assumed slippage per side.",
            "The sample is one live contract. Kite's continuous endpoint supplies daily candles for expired contracts, so this is not a five-year minute backtest.",
        ],
        "configurations": {"frozen SMA(50) + 20 bp band": "SMA(50), 20 bp dead band, MCX Gold"},
    },
    {
        "id": "extreme_minute_reversal",
        "title": "Fade extreme one-minute drops (five NSE stocks)",
        "summary": "After an unusually large one-minute decline, buy at the next traded minute open and exit at its close.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Rif & Utz (2021), Short-term stock price reversals after extreme downward price movements",
        "published": "In Nasdaq-100 data, extreme one-minute losses were followed by a reversal averaging 31% of the loss; stronger for larger and more liquid stocks.",
        "paper_url": "https://doi.org/10.1016/j.qref.2021.05.004",
        "tested_on": "RELIANCE, HDFCBANK, ICICIBANK, INFY and TCS, 2024 through November",
        "research": "docs/RESEARCH/084-gold-and-indian-stock-intraday-screen.md",
        "study": GOLD_STOCK_SCREEN,
        "instrument": "Five fixed NSE stocks",
        "logic": [
            "For each stock, set the event threshold to its 0.1% one-minute return quantile measured in 2022-2023, then freeze it.",
            "When a one-minute loss meets the threshold, buy at the next traded minute open and exit at that minute's close.",
            "Equal capital is split across five names. NSE intraday charges plus an assumed 2 bps of slippage per side.",
            "This is an India OHLC adaptation of Nasdaq tick research; it is not an exact replication.",
        ],
        "configurations": {
            "0.1% tail, one-minute hold": "per-symbol one-minute return <= training 0.1% quantile; enter next traded minute open, exit its close"
        },
    },
    {
        "id": "nse_minute_decision_tree",
        "title": "Predict next-minute direction with a shallow tree (five stocks)",
        "summary": "Fit a depth-four Gini classifier to nine indicator features and trade its next-minute direction.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Naga et al. (2024), Decision Trees for Intuitive Intraday Trading Strategies",
        "published": "Nifty-50 equities, one-minute data: depth-four Gini tree predicts next-minute return sign. The reported backtest omits trading costs.",
        "paper_url": "https://arxiv.org/abs/2405.13959",
        "tested_on": "Five fixed NSE stocks, train 2022-2023, evaluate 2024 through November",
        "research": "docs/RESEARCH/084-gold-and-indian-stock-intraday-screen.md",
        "study": GOLD_STOCK_SCREEN,
        "instrument": "Five fixed NSE stocks",
        "logic": [
            "Build one-minute return, 15-minute return, RSI14, ADX14 proxy, SMA14/close, rolling SMA/close correlation, 14- and 210-minute volatility, and VWAP14/close features.",
            "Fit one Gini decision tree per stock with maximum depth 4 on 2022-2023; predict next-minute close-return direction.",
            "Enter at the next traded minute open and exit at that minute close. Incomplete feature windows are dropped, not interpolated.",
            "Equal capital across five stocks; NSE intraday charges plus 2 bps of slippage per side. The local ADX feature is an unsmoothed proxy.",
        ],
        "configurations": {
            "Gini, depth 4, 2022-2023 train": "Gini decision tree, max depth 4, nine one-minute features, predict next-minute return sign"
        },
    },
    {
        "id": "nse_liquid_leader_laggard",
        "title": "Liquid stock leads its sector peer (NSE minute screen)",
        "summary": "Trade a same-sector stock after its more liquid peer makes a short-horizon move that it has not yet followed.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Sharma, Habib & Bowry (2018), Cluster Analysis of Stocks Using Price Movements of High Frequency Data from NSE",
        "published": "The sources document high-frequency dependence and lagged joint structure in NSE stocks; they do not publish this exact profitable rule.",
        "paper_url": "https://arxiv.org/abs/1803.09514",
        "tested_on": "HDFCBANK/ICICIBANK and TCS/INFY; train 2022-2023, evaluate 2024 through November",
        "research": "docs/RESEARCH/087-new-indian-stock-intraday-candidates.md",
        "study": STOCK_CANDIDATES,
        "instrument": "Four fixed NSE stocks",
        "logic": [
            "Within each fixed bank and IT pair, choose the higher median-turnover stock using 2022-2023 only.",
            "At five-minute decision points, if the leader moves at least 20 bp and its peer has followed less than 25% of that signed move, trade the peer in the leader's direction.",
            "Use the next traded minute open, hold five minutes, at most one entry per pair per session, and flatten by 15:10.",
            "NSE intraday charges plus 2 bp assumed slippage per side. This is a price-only adaptation, not the source's tested strategy.",
        ],
        "configurations": {"fixed rule, 2024 screen": "nse_liquid_leader_laggard"},
    },
    {
        "id": "nse_intraday_pair_convergence",
        "title": "Intraday pair spread convergence (NSE minute screen)",
        "summary": "Trade fixed sector-pair spreads back toward their recent intraday mean after a two-standard-deviation move.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Bowen, Hutchinson & O'Sullivan (2010), High Frequency Equity Pairs Trading",
        "published": "FTSE 100 high-frequency pair returns were highly sensitive to costs and execution delay; a one-period delay eliminated the reported excess returns.",
        "paper_url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1611623",
        "tested_on": "HDFCBANK/ICICIBANK and TCS/INFY; train 2022-2023, evaluate 2024 through November",
        "research": "docs/RESEARCH/087-new-indian-stock-intraday-candidates.md",
        "study": STOCK_CANDIDATES,
        "instrument": "Four fixed NSE stocks",
        "logic": [
            "For each fixed pair, calculate the log-price spread and its rolling 60-minute z-score within the session.",
            "Enter both legs at the next traded minute open when absolute z-score reaches 2; exit after it crosses back within 0.5 or after 30 minutes.",
            "Use equal notional per leg, one position per pair at a time, and flatten by 15:10.",
            "Charge both legs using date-aware NSE intraday costs plus 2 bp assumed slippage per side. The source's execution-delay finding makes costs and fills central.",
        ],
        "configurations": {"fixed rule, 2024 screen": "nse_intraday_pair_convergence"},
    },
    {
        "id": "nse_leadlag_pair_convergence",
        "title": "Trade the lagging leg of an NSE stock pair",
        "summary": "Select a lead-lag stock pair in the training sample and trade the follower when it has not yet caught up to the leader's move.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Selecting Stock Pairs for Pairs Trading While Incorporating Lead-Lag Relationship",
        "published": "The paper proposes pair selection using lead-lag information; it does not establish net profitability for this NSE rule.",
        "paper_url": "https://arxiv.org/abs/1906.05057",
        "tested_on": "Four fixed NSE stocks; train 2022-2023, evaluate 2024 through November",
        "research": "docs/RESEARCH/087-new-indian-stock-intraday-candidates.md",
        "study": STOCK_CANDIDATES,
        "instrument": "Four fixed NSE stocks",
        "logic": [
            "Using 2022-2023 only, select the ordered pair and 5/10/15-minute lag with the largest positive return correlation among the fixed bank and IT pairs.",
            "At five-minute decision points in 2024, if the leader moves at least 20 bp and the follower has followed less than 25% of that signed move, trade the follower in the leader's direction.",
            "Enter at the next traded minute open, exit after the selected lag, allow at most one trade per session, and flatten by 15:10.",
            "NSE intraday charges plus 2 bp assumed slippage per side. Pair and lag are selected in training data; no setting is selected on the evaluation window.",
        ],
        "configurations": {"training-selected pair, 2024 screen": "nse_leadlag_pair_convergence"},
    },
    {
        "id": "nse_bollinger_squeeze_expansion",
        "title": "Bollinger squeeze expansion (NSE minute screen)",
        "summary": "Trade the first close outside a short rolling range after band width contracts.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[practitioner] luckyloneranger/backtest-platform, Bollinger squeeze breakout",
        "published": "The repository lists this strategy but does not establish a verified NSE net edge.",
        "paper_url": "https://github.com/luckyloneranger/backtest-platform",
        "tested_on": "HDFCBANK, ICICIBANK, TCS and INFY; train 2022-2023, evaluate 2024 through November",
        "research": "docs/RESEARCH/088-company-and-github-intraday-strategy-screen.md",
        "study": COMPANY_GITHUB,
        "instrument": "Four fixed NSE stocks",
        "logic": [
            "Compute 20-minute Bollinger bandwidth and compare it with its trailing 60-minute 20th percentile.",
            "After a squeeze, enter when the completed close breaks the preceding 20-minute high or low; enter next traded minute open.",
            "Hold 15 minutes, at most one entry per symbol/session, flatten by 15:10.",
            "Date-aware NSE charges plus 2 bp assumed slippage per side; fixed India adaptation. Run with make company-github-intraday.",
        ],
        "configurations": {"20/60 squeeze, 15-minute hold": "nse_bollinger_squeeze_expansion"},
    },
    {
        "id": "nse_initial_balance_failure",
        "title": "Initial-balance failure fade (NSE minute screen)",
        "summary": "Fade a first-hour range break after a minute bar closes back inside the range.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[practitioner] om-gorakhia/nse-algo-trading-system, Initial Balance failure rules",
        "published": "The repository reports selected configurations but does not independently establish their performance.",
        "paper_url": "https://github.com/om-gorakhia/nse-algo-trading-system",
        "tested_on": "HDFCBANK, ICICIBANK, TCS and INFY; train 2022-2023, evaluate 2024 through November",
        "research": "docs/RESEARCH/088-company-and-github-intraday-strategy-screen.md",
        "study": COMPANY_GITHUB,
        "instrument": "Four fixed NSE stocks",
        "logic": [
            "Define initial balance as 09:16 through 10:14 high/low.",
            "After 10:15, fade the first bar whose high/low crosses a boundary but whose close returns inside.",
            "Enter next traded minute open and hold 30 minutes; at most one entry per symbol/session; flatten by 15:10.",
            "Date-aware NSE charges plus 2 bp assumed slippage per side; failed acceptance, not ORB continuation. Run with make company-github-intraday.",
        ],
        "configurations": {
            "60-minute initial balance, 30-minute hold": "nse_initial_balance_failure"
        },
    },
    {
        "id": "nse_time_adaptive_momentum_reversion",
        "title": "Training-selected time-of-day regime switch (NSE minute screen)",
        "summary": "Choose momentum or reversion by session segment using training-period outcomes only.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[practitioner] luckyloneranger/backtest-platform, time-adaptive strategy",
        "published": "The repository lists a time-adaptive strategy; this screen freezes selection using 2022-2023 only.",
        "paper_url": "https://github.com/luckyloneranger/backtest-platform",
        "tested_on": "HDFCBANK, ICICIBANK, TCS and INFY; train 2022-2023, evaluate 2024 through November",
        "research": "docs/RESEARCH/088-company-and-github-intraday-strategy-screen.md",
        "study": COMPANY_GITHUB,
        "instrument": "Four fixed NSE stocks",
        "logic": [
            "Select momentum or fade of the preceding five-minute return separately for fixed open, midday and late-day windows, using the higher mean signed next-five-minute training return.",
            "Freeze the three selections after 2023; take one trade per segment per symbol/session in 2024.",
            "Enter next traded minute open and exit five minutes later; flatten by 15:10.",
            "Date-aware NSE charges plus 2 bp assumed slippage per side; high-overfit-risk selector. Run with make company-github-intraday.",
        ],
        "configurations": {
            "training-selected mode by segment": "nse_time_adaptive_momentum_reversion"
        },
    },
    {
        "id": "nse_value_area_acceptance_breakout",
        "title": "Prior-session value-area acceptance breakout (NSE proxy screen)",
        "summary": "Follow two completed closes beyond a prior-session value-area boundary.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[practitioner] pedrobraiti/volume-profile-trading, value-area breakout",
        "published": "The source's US/Brazil study reports mixed results and finds no robust standalone economic edge.",
        "paper_url": "https://github.com/pedrobraiti/volume-profile-trading",
        "tested_on": "HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November; typical-price OHLCV profile proxy",
        "research": "docs/RESEARCH/088-company-and-github-intraday-strategy-screen.md",
        "study": COMPANY_GITHUB,
        "instrument": "Four fixed NSE stocks; HLC3 profile proxy",
        "logic": [
            "Build previous session's 70% value area by assigning each minute's volume to its HLC3 price rounded to ₹0.05.",
            "Enter next minute after two closes outside VAH/VAL; hold ten minutes, one trade per symbol/session.",
            "Flatten by 15:10; date-aware NSE charges plus 2 bp assumed slippage per side.",
            "OHLCV proxy cannot recover true volume-at-price. Run with make company-github-intraday.",
        ],
        "configurations": {
            "two closes beyond prior VA, 10-minute hold (proxy)": "nse_value_area_acceptance_breakout"
        },
    },
    {
        "id": "nse_value_area_edge_to_edge",
        "title": "Value-area edge-to-edge traversal (NSE proxy screen)",
        "summary": "Trade toward the opposite prior-session value-area edge after a confirmed re-entry.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[practitioner] pedrobraiti/volume-profile-trading, Edge-to-Edge",
        "published": "The source's final falsification attributes much of the apparent result to exposure, not standalone alpha.",
        "paper_url": "https://github.com/pedrobraiti/volume-profile-trading",
        "tested_on": "HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November; typical-price OHLCV profile proxy",
        "research": "docs/RESEARCH/088-company-and-github-intraday-strategy-screen.md",
        "study": COMPANY_GITHUB,
        "instrument": "Four fixed NSE stocks; HLC3 profile proxy",
        "logic": [
            "Use previous session's 70% HLC3 volume-profile value area, assigning each minute's volume to HLC3 rounded to ₹0.05.",
            "After price re-enters from outside and confirms with a second close inside, trade toward the far value-area edge; fixed 30-minute cap.",
            "At most one trade per symbol/session; enter next traded minute and flatten by 15:10.",
            "Date-aware NSE charges plus 2 bp assumed slippage per side; proxy levels are approximate. Run with make company-github-intraday.",
        ],
        "configurations": {
            "re-entry traversal, 30-minute cap (proxy)": "nse_value_area_edge_to_edge"
        },
    },
    {
        "id": "nse_volume_exhaustion_no_supply",
        "title": "Low-volume new-low exhaustion (NSE minute screen)",
        "summary": "Buy a new 20-minute low only when the signal minute's volume is below its trailing median.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[practitioner] pedrobraiti/volume-profile-trading, volume exhaustion / no-supply",
        "published": "The source reports a modest volume signal in US index ETFs but rejects robust standalone alpha after falsification.",
        "paper_url": "https://github.com/pedrobraiti/volume-profile-trading",
        "tested_on": "HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November",
        "research": "docs/RESEARCH/088-company-and-github-intraday-strategy-screen.md",
        "study": COMPANY_GITHUB,
        "instrument": "Four fixed NSE stocks",
        "logic": [
            "Find the first new 20-minute low whose signal-minute volume is below the preceding 20-minute median.",
            "Enter long at the next traded minute open and exit ten minutes later; no mirrored short without separate evidence.",
            "At most one trade per symbol/session; flatten by 15:10.",
            "Date-aware NSE charges plus 2 bp assumed slippage per side; candle adaptation, not volume-at-price replication. Run with make company-github-intraday.",
        ],
        "configurations": {
            "new 20-minute low, below-median volume, 10-minute hold": "nse_volume_exhaustion_no_supply"
        },
    },
    {
        "id": "nse_value_area_80_rule",
        "title": "80% value-area traversal rule (NSE proxy falsification)",
        "summary": "Test whether a session that opens outside prior value and re-enters traverses the full area.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[practitioner] pedrobraiti/volume-profile-trading, 80% Rule",
        "published": "The source finds the traversal rate below 80% and reports losses after costs; kept as a negative-control screen.",
        "paper_url": "https://github.com/pedrobraiti/volume-profile-trading",
        "tested_on": "HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November; typical-price OHLCV profile proxy",
        "research": "docs/RESEARCH/088-company-and-github-intraday-strategy-screen.md",
        "study": COMPANY_GITHUB,
        "instrument": "Four fixed NSE stocks; HLC3 profile proxy",
        "logic": [
            "Use previous session 70% HLC3 volume-profile value area, rounded to ₹0.05 bins.",
            "If the first tradable open lies outside value and price re-enters within 30 minutes, trade toward the opposite boundary with a 30-minute cap.",
            "At most one trade per symbol/session; next-minute entry; flatten by 15:10.",
            "Date-aware NSE charges plus 2 bp assumed slippage per side. Negative-control screen. Run with make company-github-intraday.",
        ],
        "configurations": {
            "outside open then re-entry, 30-minute cap (proxy)": "nse_value_area_80_rule"
        },
    },
    {
        "id": "nse_poc_rejection_rotation",
        "title": "POC reclaim and rotation (NSE proxy screen)",
        "summary": "Trade a completed-bar rejection/reclaim of the prior-session point of control.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[practitioner] pedrobraiti/volume-profile-trading, POC reversion",
        "published": "The source's volume-profile geometry does not show robust standalone economic alpha after falsification.",
        "paper_url": "https://github.com/pedrobraiti/volume-profile-trading",
        "tested_on": "HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November; typical-price OHLCV profile proxy",
        "research": "docs/RESEARCH/088-company-and-github-intraday-strategy-screen.md",
        "study": COMPANY_GITHUB,
        "instrument": "Four fixed NSE stocks; HLC3 profile proxy",
        "logic": [
            "Calculate prior session's POC from HLC3 prices weighted by minute volume, rounded to ₹0.05 bins.",
            "If a completed bar crosses/reclaims POC after approaching from one side, enter in the reclaim direction at next open.",
            "Hold 15 minutes, one trade per symbol/session, and flatten by 15:10.",
            "Date-aware NSE charges plus 2 bp assumed slippage per side. POC is an OHLCV proxy with a weak prior. Run with make company-github-intraday.",
        ],
        "configurations": {
            "prior POC reclaim, 15-minute hold (proxy)": "nse_poc_rejection_rotation"
        },
    },
    {
        "id": "nse_inventory_skewed_market_making",
        "title": "Inventory-skewed passive market making (data blocked)",
        "summary": "Quote both sides around fair value, skew quotes to manage inventory, and withdraw when order flow becomes toxic.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[practitioner] Optiver market-making disclosures and Avellaneda-Stoikov public model implementations",
        "published": "Public firm materials describe market making at a high level but do not disclose this rule or establish NSE returns.",
        "paper_url": "https://www.optiver.com/what-we-do/",
        "tested_on": "Not tested: current archive contains candles, not order-book updates or queue/fill history",
        "research": "docs/RESEARCH/088-company-and-github-intraday-strategy-screen.md",
        "study": COMPANY_GITHUB,
        "instrument": "NSE single-stock order book; data unavailable",
        "logic": [
            "Estimate fair value from a live mid/microprice and volatility; maintain passive bid and ask quotes.",
            "Shift both quotes against accumulated inventory; stop quoting when short-horizon signed order flow predicts adverse selection.",
            "Evaluate with queue position, partial fills, latency, inventory carry and actual NSE charges.",
            "Blocked. Needs timestamped depth deltas, signed trade prints, queue/fill records and latency-aware replay; minute OHLCV is insufficient. Run with make company-github-intraday after acquiring those feeds.",
        ],
        "configurations": {
            "inventory skew + toxicity gate (blocked)": "nse_inventory_skewed_market_making"
        },
    },
    {
        "id": "nse_cross_venue_same_stock_dislocation",
        "title": "NSE-BSE same-stock dislocation (data blocked)",
        "summary": "Trade a synchronized price gap between the same share listed on NSE and BSE after costs and executable depth.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[practitioner] Public multi-venue market-maker disclosures; India-specific research adaptation",
        "published": "Company reports establish multi-venue activity, not a disclosed cross-venue signal or India backtest.",
        "paper_url": "https://www.imc.com/in/corporate-news/IMC-launches-2024-annual-report",
        "tested_on": "Not tested: local minute archive has NSE candles only",
        "research": "docs/RESEARCH/088-company-and-github-intraday-strategy-screen.md",
        "study": COMPANY_GITHUB,
        "instrument": "Dual-listed NSE/BSE equities; synchronized quote history unavailable",
        "logic": [
            "Compare synchronized, executable NSE and BSE quotes for the same share, after aligning timestamps and corporate actions.",
            "Trade the cheaper venue long and richer venue short only when the spread clears both venue costs, expected slippage, and unwind risk.",
            "Use matched quantities, enforce borrow/short-sale constraints and close both legs together.",
            "Blocked. Needs synchronized venue quote/trade history, depth, exchange-specific costs and fill records. Current NSE candle data cannot establish executable arbitrage. Run with make company-github-intraday after acquiring those feeds.",
        ],
        "configurations": {
            "synchronized NSE-BSE spread (blocked)": "nse_cross_venue_same_stock_dislocation"
        },
    },
    {
        "id": "nse_ema_macd_swing_pullback",
        "title": "EMA pullback with MACD confirmation (NSE minute screen)",
        "summary": "Join an intraday trend after price revisits EMA-20 and MACD histogram confirms, using a recent swing stop and 1R target.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[GitHub] spagnola-analytics/intraday-strategies, EMA + MACD + support/resistance",
        "published": "The repository describes this on MES futures; its results do not establish an NSE stock edge.",
        "paper_url": "https://github.com/spagnola-analytics/intraday-strategies",
        "tested_on": "HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November",
        "research": "docs/RESEARCH/089-github-intraday-followup.md",
        "study": GITHUB_FOLLOWUP,
        "instrument": "Four fixed NSE stocks",
        "logic": [
            "Compute 1-minute EMA(20) and MACD(12,26,9) from that session's closes.",
            "Long: previous close is above EMA-20, the signal bar touches EMA-20 and closes back above it, and MACD histogram is positive. Reverse conditions for a short.",
            "Enter at the next traded minute open; stop at the signal bar and previous four bars' extreme; target 1R. Ignore a setup with stop distance above 1%.",
            "At most one trade per stock/session. If stop and target both trade in a bar, stop first; flatten by 15:10. Date-aware NSE intraday charges plus 2 bp assumed slippage per side. Run with make github-followup-intraday.",
        ],
        "configurations": {
            "EMA-20/MACD pullback, five-bar swing stop, 1R target": "nse_ema_macd_swing_pullback"
        },
    },
    {
        "id": "nse_overnight_extreme_fade",
        "title": "Overnight high/low fade (NSE adaptation blocked)",
        "summary": "Fade a first-hour touch of an overnight extreme with a fixed 1R target.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[GitHub] spagnola-analytics/intraday-strategies, M4 overnight high/low fade",
        "published": "The repository applies this to the MES overnight futures session; the NSE cash adaptation has not been tested.",
        "paper_url": "https://github.com/spagnola-analytics/intraday-strategies",
        "tested_on": "Not tested: no NSE cash overnight traded-price history in the local minute archive",
        "research": "docs/RESEARCH/089-github-intraday-followup.md",
        "study": GITHUB_FOLLOWUP,
        "instrument": "NSE cash; overnight data unavailable",
        "logic": [
            "Source rule fades the first RTH touch of the prior overnight high or low, with first-touch-only entries and 1:1 risk/reward.",
            "Do not substitute prior cash-session high/low for overnight futures extremes; that would change the tested level and market session.",
            "Required history: timestamped NSE cash-equity pre-open/overnight executable prices and corresponding volume, plus realistic open auction fills.",
            "Data blocked, so no backtest result exists. Run with make github-followup-intraday after the required history is available.",
        ],
        "configurations": {
            "MES overnight extreme first-touch fade (blocked)": "nse_overnight_extreme_fade"
        },
    },
    {
        "id": "nse_surge_pullback_new_high",
        "title": "Surge, pullback and first higher-high breakout (NSE screen)",
        "summary": "After a sharp intraday surge and controlled pullback, buy the first green higher-high bar with positive MACD, above-VWAP price and strong relative volume.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[GitHub] woshishuaige2/ross-cameron-trading-strategy, pullback breakout",
        "published": "The GitHub author describes a US small-cap strategy; the repository's code and README disagree on several thresholds, and neither proves NSE profitability.",
        "paper_url": "https://github.com/woshishuaige2/ross-cameron-trading-strategy",
        "tested_on": "RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November",
        "research": "docs/RESEARCH/090-github-surge-pullback-breakout.md",
        "study": GITHUB_MOMENTUM_PULLBACK,
        "instrument": "Five fixed NSE stocks",
        "logic": [
            "Use the repository code defaults: a 2% surge over a 5-20-bar segment; a 0.3%-5% retracement from a recent high; then a green candle making a higher high than the prior candle.",
            "Require positive MACD(12,26,9), completed close above session VWAP, last-two-bar mean volume at least 2x the preceding up-to-eight-bar mean, fewer than four red candles in the last five, and no specified topping wick.",
            "Enter next traded minute open; stop 1% below pullback low; target 20% above entry; exit on stop, target, a later candle-under-candle signal, or 15:10. One trade per symbol/session.",
            "Date-aware NSE charges plus 2 bp assumed slippage per side. Source README/config thresholds conflict and the source universe uses premarket/catalyst context unavailable here. Run with make github-momentum-pullback-intraday.",
        ],
        "configurations": {
            "2% surge, pullback, higher-high + MACD/VWAP/RVOL filters": "nse_surge_pullback_new_high"
        },
    },
    {
        "id": "nse_inside_bar_breakout_2r",
        "title": "Inside-bar compression breakout with structure stop (NSE screen)",
        "summary": "After a strict 5-minute inside bar, trade a close-confirmed break of its range with the opposite inside-bar extreme as stop and a 2R target.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[GitHub] fmzquant/strategies, Inside-Bar Breakout Strategy",
        "published": "The repository publishes rule code but no independently verifiable performance. A separate 2025-2026 screen reported PF 0.98 across four non-Indian markets; it is a negative prior, not NSE evidence.",
        "paper_url": "https://github.com/fmzquant/strategies/blob/master/%E5%86%85%E9%83%A8%E6%94%B6%E6%95%9B%E7%AA%81%E7%A0%B4%E7%AD%96%E7%95%A5Inside-Bar-Breakout-Strategy.md",
        "tested_on": "RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November",
        "research": "docs/RESEARCH/093-github-inside-bar-breakout.md",
        "study": INSIDE_BAR,
        "instrument": "Five fixed NSE stocks",
        "logic": [
            "Skip the first 09:15 minute bin. Aggregate the remaining one-minute OHLCV to 5-minute bars; require at least four observed minutes in each bar.",
            "A pattern bar is inside when its high is strictly below the prior 5-minute bar's high and its low is strictly above that bar's low.",
            "On the immediately following 5-minute bar, require a close above the inside-bar high (long) or below its low (short). Enter at the next 5-minute bar open.",
            "Stop at the opposite inside-bar extreme; target 2R from the actual entry. If the next open makes risk non-positive, skip. At most one trade per stock/session.",
            "Flatten by 15:10. If stop and target touch within the same 5-minute bar, assume the stop filled first; stop gaps fill at the open. Date-aware NSE intraday charges plus 2 bp assumed slippage per side. Run with make inside-bar-intraday.",
        ],
        "configurations": {
            "5-minute inside-bar close break, structural stop, 2R": "nse_inside_bar_breakout_2r"
        },
    },
    {
        "id": "nse_hikkake_failed_inside_bar",
        "title": "Hikkake failed inside-bar breakout (NSE screen)",
        "summary": "After an inside bar and a one-sided range break, enter on a stop through the opposite inside-bar edge within three bars.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[practitioner] Dan Chesler Hikkake false-breakout rule; Oxford Strategy specification",
        "published": "Oxford Strategy reports a 34-year, 42-futures-market study and prefers holding periods longer than ten bars; its evidence is not an Indian-equity intraday result.",
        "paper_url": "https://oxfordstrat.com/trading-strategies/hikkake-pattern/",
        "tested_on": "RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November",
        "research": "docs/RESEARCH/094-hikkake-failed-breakout.md",
        "study": HIKKAKE,
        "instrument": "Five fixed NSE stocks",
        "logic": [
            "Aggregate the post-09:15 one-minute archive into 5-minute bars, retaining bars with at least four observed minutes. Require a strict inside bar followed by the Hikkake opposite-direction high/low pattern.",
            "Place a one-tick stop entry beyond the inside-bar edge, active for the next three bars. Fill at the trigger or a worse opening gap; skip if the trigger never occurs.",
            "Use the tighter of a one-tick pattern stop beyond the complete formation through entry and the source's 6 x ATR(20) stop. There is no profit target; flatten by 15:10, with at most one trade per stock/session.",
            "If the trigger and stop both touch in one 5-minute bar, assume stop first. Apply date-aware NSE intraday charges and 2 bp assumed slippage per side. This same-session adaptation differs from the source's preferred multi-day holding period. Run with make hikkake-intraday.",
        ],
        "configurations": {
            "5-minute Hikkake, 3-bar trigger, pattern/6x ATR stop, 15:10 exit": "nse_hikkake_failed_inside_bar"
        },
    },
    {
        "id": "nse_github_ema_5_15_crossover",
        "title": "EMA(5/15) crossover with next-bar reversal (NSE adaptation)",
        "summary": "Trade each completed 5-minute fast/slow EMA crossover at the next bar open; reverse on the opposite cross and flatten before the close.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[GitHub] mohanyadu/Quantitative-Trading-System-NIFTY-5-Min-",
        "published": "The public README reports negative train and test returns for its index baseline before costs and zero trades for its XGBoost filter. Its own future-work list includes costs and more validation.",
        "paper_url": "https://github.com/mohanyadu/Quantitative-Trading-System-NIFTY-5-Min-",
        "tested_on": "RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November",
        "research": "docs/RESEARCH/095-github-ema-crossover-nse-screen.md",
        "study": GITHUB_EMA,
        "instrument": "Five fixed NSE stocks",
        "logic": [
            "Aggregate the post-09:15 minute OHLCV archive into 5-minute bars. Calculate recursive EMA(5) and EMA(15) continuously per stock, warmed on available pre-2024 bars.",
            "When EMA(5) crosses above EMA(15), go long at the next contiguous 5-minute open; cross below to go short. At an opposite cross, close and reverse at that next-bar open.",
            "Carry no position overnight; flatten at 15:10. Split ₹1,000,000 equally across the five fixed stocks; apply date-aware NSE intraday charges and 2 bp assumed slippage per side.",
            "This test omits the source's HMM regime filter because its options IV/PCR/Greeks and futures-basis inputs are absent from the local stock OHLCV archive. Run with make github-ema-crossover-intraday.",
        ],
        "configurations": {
            "5-minute EMA(5/15) price-only cross, next-open reverse, 15:10 exit": "nse_github_ema_5_15_crossover"
        },
    },
    {
        "id": "nse_supertrend_mtf_volume_reclaim",
        "title": "Multi-timeframe Supertrend re-alignment with volume confirmation",
        "summary": "Go long when a 15-minute Supertrend flips back bullish with volume expansion while the latest completed hourly Supertrend remains bullish.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[practitioner] LeadFinn, Supertrend Indicator Strategy: Indian Market Rules & Verified Backtest",
        "published": "LeadFinn reports that raw Supertrend flips lost after costs in its NSE tests; its specific multi-timeframe alignment setup is described but no setup-level result is reported.",
        "paper_url": "https://leadfinn.co/strategies/supertrend",
        "tested_on": "RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November",
        "research": "docs/RESEARCH/096-supertrend-mtf-volume-realignment.md",
        "study": SUPERTREND_MTF,
        "instrument": "Five fixed NSE stocks",
        "logic": [
            "Calculate Supertrend(10,3) on continuous 15-minute and 60-minute OHLC bars derived from the local minute archive. Use only completed hourly bars as the higher-timeframe regime.",
            "After the source's opening volatility window, go long when 15-minute Supertrend flips from bearish to bullish while the latest completed hourly Supertrend is bullish and 15-minute volume crosses above its trailing 20-bar mean.",
            "Enter at the next 15-minute open. Set the stop to the 15-minute Supertrend line at signal close and target 2R; if stop and target touch within one minute, assume stop first.",
            "Take at most one trade per stock/session and flatten at 15:10. Use ₹200,000 notional per stock, date-aware NSE intraday charges, and 2 bp assumed slippage per side. Run with make supertrend-alignment-intraday.",
        ],
        "configurations": {
            "15m/60m Supertrend(10,3) realignment + 20-bar volume cross, 2R": "nse_supertrend_mtf_volume_reclaim"
        },
    },
    {
        "id": "nse_github_keltner_channel_breakout",
        "title": "Keltner Channel close breakout (GitHub baseline)",
        "summary": "Go long when a completed 5-minute close breaks above EMA(20) + 2 ATR; exit on a close below EMA(20).",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[GitHub] cloudQuant/backtrader Keltner Channel strategy test",
        "published": "The source code defines a long-only upper-band close breakout and EMA-midline close exit with period 20 and ATR multiplier 2.0. It presents a demonstration, not independent Indian evidence.",
        "paper_url": "https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volatility/test_108_keltner_channel_strategy.py",
        "tested_on": "RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November",
        "research": "docs/RESEARCH/106-github-keltner-channel-nse-screen.md",
        "study": GITHUB_KELTNER,
        "instrument": "Five fixed NSE stocks",
        "logic": [
            "Build 5-minute bars from local NSE one-minute OHLCV, omitting the first 09:15 print bin. Calculate continuous EMA(20) and Wilder ATR(20) per stock, including the prior close when measuring true range.",
            "Enter long at the next contiguous 5-minute open after a completed close above EMA(20) + 2 x ATR(20). Exit at the next contiguous open after a completed close below EMA(20). Do not hold overnight; flatten at 15:10.",
            "Use ₹200,000 per stock from ₹1,000,000 total capital. Apply date-aware NSE intraday charges plus 2 bp assumed slippage per side. The source's suggested volume filter is optional, so this fixed screen omits it. Run with make github-keltner-intraday.",
            "This is a close-price adaptation of the source. Keltner breakout broadly overlaps trend/breakout families, including the existing squeeze card; the ATR channel and EMA exit are the source-specific tested rule.",
        ],
        "configurations": {
            "5-minute long Keltner(20, 2 ATR), next-open entry/midline exit": "nse_github_keltner_channel_breakout"
        },
    },
    {
        "id": "nse_github_donchian_breakout",
        "title": "Donchian channel breakout (GitHub 5-minute rule)",
        "summary": "Enter long on a close above the prior 78-bar high and exit on a close below the prior 39-bar low.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[GitHub] JamesRPowell/Donchain-Breakout",
        "published": "The source's 5-minute script uses a 78-bar entry high and 39-bar exit low, then applies the signal one bar later. Its README reports negative out-of-sample Sharpe on several US tickers; it does not establish an NSE edge.",
        "paper_url": "https://github.com/JamesRPowell/Donchain-Breakout/blob/main/TurtleDonchain_Intraday.py",
        "tested_on": "RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November",
        "research": "docs/RESEARCH/107-github-donchian-intraday-nse-screen.md",
        "study": GITHUB_DONCHIAN,
        "instrument": "Five fixed NSE stocks",
        "logic": [
            "Aggregate the local one-minute OHLCV to 5-minute bars, omitting the first 09:15 print bin. For each completed bar, compute the highest high of the prior 78 bars and the lowest low of the prior 39 bars; exclude the current bar from both channels.",
            "Enter long at the next contiguous 5-minute open after a close above the prior 78-bar high. Exit at the next open after a close below the prior 39-bar low. Reset positions each session and square off by 15:10; channel history continues across sessions.",
            "Use ₹200,000 per stock from ₹1,000,000 total capital, date-aware NSE intraday charges and 2 bp assumed slippage per side. This intraday adaptation flattens daily although the source carries positions across its 60-day sample. Run with make github-donchian-intraday.",
            "This is a fixed channel-breakout rule and is adjacent to existing ORB and Keltner/Bollinger breakout screens; the 78/39 structural channel itself is the source-specific setup.",
        ],
        "configurations": {
            "5-minute long Donchian 78-bar entry / 39-bar exit, next-open fills": "nse_github_donchian_breakout"
        },
    },
    {
        "id": "nse_github_prior_day_pivot_breakout",
        "title": "Prior-day floor pivot breakout (GitHub rule)",
        "summary": "Go long above prior-day R1 and short below prior-day S1, reversing at the opposite level and flattening intraday.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[GitHub] FMZ dynamic support/resistance pivot strategy by HPotter",
        "published": "The public script defines PP=(prior H+L+C)/3, R1=2*PP-L and S1=2*PP-H; it holds the direction until the opposite threshold. It is educational code with no verified NSE performance result.",
        "paper_url": "https://github.com/fmzquant/strategies/blob/master/%E5%8A%A8%E6%80%81%E6%94%AF%E6%92%91%E9%98%BB%E5%8A%9B%E5%9B%9E%E6%B5%8B%E7%AD%96%E7%95%A5Dynamic-Pivot-Point-Backtest-Strategy.md",
        "tested_on": "RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November",
        "research": "docs/RESEARCH/108-github-prior-day-pivot-nse-screen.md",
        "study": GITHUB_PIVOT,
        "instrument": "Five fixed NSE stocks",
        "logic": [
            "Calculate today's floor pivot from the previous session's H/L/C: PP=(H+L+C)/3, R1=2*PP-L, S1=2*PP-H.",
            "After a completed 5-minute close above R1, enter long at the next contiguous 5-minute open; below S1, enter short. Hold through closes between levels and reverse at the next open after a close beyond the opposite level.",
            "Do not hold overnight; flatten at 15:10. Use ₹200,000 per stock from ₹1,000,000 total capital, date-aware NSE intraday charges and 2 bp assumed slippage per side. Run with make github-pivot-intraday.",
            "The levels come from prior-session daily ranges, so this is distinct from current-session ORB levels. It remains part of the broad breakout family and is a price-only adaptation of an educational GitHub script.",
        ],
        "configurations": {
            "5-minute prior-day floor pivot R1/S1 breakout, reverse at opposite level": "nse_github_prior_day_pivot_breakout"
        },
    },
    {
        "id": "nse_github_engulfing_volume_rsi",
        "title": "Engulfing candle with volume and RSI filters (GitHub rule)",
        "summary": "Trade strict 5-minute engulfing patterns when volume expands and RSI confirms an oversold or overbought setup, with a fixed 5R target.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[GitHub] kavyansh34 Engulfing candle backtester",
        "published": "The public example is for BTCUSDT and describes RSI(14) below 40 for longs, above 60 for shorts, volume above EMA(14), and a 1:5 risk/reward target. It provides no verified Indian equity result.",
        "paper_url": "https://github.com/kavyansh34/Engulfing_candle_backtester",
        "tested_on": "RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November",
        "research": "docs/RESEARCH/109-github-engulfing-volume-rsi-nse.md",
        "study": GITHUB_ENGULFING,
        "instrument": "Five fixed NSE stocks",
        "logic": [
            "Require strict two-candle body engulfing with opposite candle colors. On the completed signal bar, require signal volume above the prior-bar volume EMA(14), and RSI(14) below 40 for a long or above 60 for a short.",
            "Enter at the next contiguous 5-minute open. Stop beyond the outer low/high of the engulfing pair and set a fixed 5R target. If stop and target both trade in one bar, assume the stop fills first; model gap-through stops at the open.",
            "Allow one trade per stock per session. Risk 1% of each ₹200,000 stock sleeve, capped by sleeve notional; flatten at 15:10. Apply date-aware NSE charges and 2 bp assumed slippage per side. Run with make github-engulfing-intraday.",
            "The GitHub implementation contains ambiguous pattern checks, a faulty long-stop expression, and omits costs; this is a corrected, independently coded rule adaptation, not a replication of its reported performance.",
        ],
        "configurations": {
            "5-minute engulfing + prior volume EMA(14) + RSI(14), 5R": "nse_github_engulfing_volume_rsi"
        },
    },
    {
        "id": "nse_github_3bar_atr_momentum_burst",
        "title": "Three-bar ATR momentum burst with volume confirmation (GitHub rule)",
        "summary": "Follow a 5-minute move larger than 1.5 ATR when the signal bar has over twice its preceding average volume, with an ATR trailing stop.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[GitHub] luckyloneranger/backtest-platform intraday_momentum",
        "published": "The README specifies a 3-bar burst above 1.5 ATR, volume above 2x average and 1x ATR trailing stop. Its +32%/+39% claim belongs to a combined regime-adaptive portfolio, not this signal in isolation.",
        "paper_url": "https://github.com/luckyloneranger/backtest-platform/blob/main/strategies/strategies/deterministic/intraday_momentum.py",
        "tested_on": "RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November",
        "research": "docs/RESEARCH/110-github-momentum-burst-nse.md",
        "study": GITHUB_MOMENTUM_BURST,
        "instrument": "Five fixed NSE stocks",
        "logic": [
            "On completed 5-minute bars after the 14-period ATR is available, calculate the close-to-close move over three bar intervals. Enter in its direction if the absolute move exceeds 1.5 ATR and signal-bar volume is greater than twice the mean of the preceding up to 20 bars.",
            "Enter at the next contiguous 5-minute open. Initialize the stop one ATR beyond the signal close and trail it by one ATR using completed bars only. Model stop gaps at the open and do not assume favorable order inside a bar.",
            "Warm up for six bars, allow at most two round trips per stock/session, and flatten at 15:00. Allocate 3% of ₹1,000,000 portfolio capital per position, capped at ₹200,000 per stock. Apply date-aware NSE intraday charges and 2 bp assumed slippage per side. Run with make github-momentum-burst-intraday.",
            "The rule is a standalone test of the source's intraday_momentum component; the source's reported portfolio-combiner performance is not attributed to this component. It is distinct from the repository's surge-then-pullback setup, though both belong to the broader momentum family.",
        ],
        "configurations": {
            "5-minute 3-bar move >1.5 ATR, volume >2x prior mean, 1 ATR trail": "nse_github_3bar_atr_momentum_burst"
        },
    },
    {
        "id": "nse_github_connors_rsi2_intraday_pullback",
        "title": "Connors RSI(2) pullback with SMA trend filter (GitHub rule)",
        "summary": "Buy oversold 5-minute pullbacks above the 200-bar trend SMA, or short overbought bars below it, and exit at the 5-bar SMA.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[GitHub] jesse-ai/example-strategies RSI2",
        "published": "The repository implements Connors RSI(2): SMA(200) trend filter, RSI(2) thresholds 10/90, and exit at SMA(5). It gives no verified Indian intraday result.",
        "paper_url": "https://github.com/jesse-ai/example-strategies/blob/master/RSI2/__init__.py",
        "tested_on": "RELIANCE, HDFCBANK, ICICIBANK, TCS and INFY; 2024 through November",
        "research": "docs/RESEARCH/111-github-rsi2-intraday-nse.md",
        "study": GITHUB_RSI2,
        "instrument": "Five fixed NSE stocks",
        "logic": [
            "Adapt the source's bar-based SMA(200), RSI(2) and SMA(5) periods to completed 5-minute bars. Use continuous indicators across sessions; long when close is above SMA(200) and RSI(2) is at most 10, short when below SMA(200) and RSI(2) is at least 90.",
            "Enter at the next contiguous 5-minute open. Exit when a completed close is above SMA(5) for a long or below SMA(5) for a short, filling at the next open. No stop or target is added; force flat at 15:10.",
            "Allocate ₹200,000 notional per stock from ₹1,000,000 capital, with at most one position per stock at a time. Apply date-aware NSE intraday charges and 2 bp assumed slippage per side. Run with make github-rsi2-intraday.",
            "The original rule is a general chart-timeframe strategy, not an Indian 5-minute study. This fixed 5-minute adaptation is distinct from existing extreme-minute fades and VWAP/OU mean reversion but belongs to the broader pullback/reversion family.",
        ],
        "configurations": {
            "5-minute Connors RSI(2) <=10/>=90, SMA(200) trend, SMA(5) exit": "nse_github_connors_rsi2_intraday_pullback"
        },
    },
    {
        "id": "fii_index_futures_position_follow",
        "title": "Lagged FII index-futures positioning (NSE screen)",
        "summary": "Trade five liquid NSE stocks in the direction of the change in FII index-futures net open interest, with a conservative reporting lag.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Dhingra, Gandhi & Bulsara (2016), with NSE participant-wise OI adaptation",
        "published": "The source reports daily FII selling/withdrawal is associated with higher market volatility; it does not specify this OI-based direction rule. NSE OI is positions, not cash flows or intraday trades.",
        "paper_url": "https://www.sciencedirect.com/science/article/pii/S0970389616300854",
        "tested_on": "RELIANCE, HDFCBANK, ICICIBANK, INFY and TCS; 2024 through November",
        "research": "docs/RESEARCH/097-fii-dii-entry-exit-impact.md",
        "study": FII_PARTICIPANT_OI,
        "instrument": "Five fixed NSE stocks, market-wide signal",
        "logic": [
            "Compute FII index-futures net OI as Future Index Long minus Future Index Short. The signal is the sign of its change between reports; this is a positioning proxy, not cash FII entry/exit.",
            "Apply the signal two full NSE sessions after the later report date to avoid same-day publication lookahead. Long for a positive change and short for a negative change; a zero change is flat.",
            "Enter at the first traded minute open at 09:16 and exit at the first traded minute open at 15:10. Apply date-aware NSE intraday charges and 2 bp assumed slippage per side; allocate ₹200,000 notional per stock.",
            "DII positioning is recorded separately as agreement/opposition context, not used to alter direction. This is a fixed 2024 screen, not a paper replication. Run with make fii-positioning-intraday.",
        ],
        "configurations": {
            "FII index-futures net OI change sign, two-session lag": "nse_fii_index_futures_oi_lagged_direction"
        },
    },
    {
        "id": "nse_cost_aware_30m_random_forest",
        "title": "Cost-aware 30-minute Random Forest signal (NSE adaptation)",
        "summary": "Predicts whether a 30-minute NSE stock move can exceed modeled two-sided costs using a cost-aware Random Forest target.",
        "kind": "quant",
        "shape": "event",
        "asset_class": "equity",
        "timeframe": "1m",
        "source": "[paper] Gaona, Rangel-Madariaga & Uribe (2026), Intraday trading strategy selection under transaction costs with machine learning",
        "published": "On 40 non-Indian assets, the paper reports 30 minutes as the most selected horizon and only a small subset profitable after its assumed costs; this fixed Indian adaptation uses one Random Forest and is tested independently.",
        "paper_url": "https://doi.org/10.3389/fams.2026.1888767",
        "tested_on": "RELIANCE, HDFCBANK, ICICIBANK, INFY and TCS; train 2022-2023, evaluate 2024 through November",
        "research": "docs/RESEARCH/103-cost-aware-ml-intraday-nse.md",
        "study": COST_AWARE_ML,
        "instrument": "Five fixed NSE large-cap stocks",
        "logic": [
            "Build the paper's price/volume indicator families: 10-period SMA/EMA, session VWAP, MACD(12,26,9), stochastic(14,3), one-period momentum/ROC, Bollinger(20,2) and RSI(14); use only completed one-minute bars.",
            "Train a three-class Random Forest on 2022-2023. Label a 30-minute next-open-to-open move long/short only when the historical move exceeds modeled date-aware two-sided NSE costs; otherwise label it flat.",
            "When the model predicts long or short, enter at the next traded minute open and exit 30 minutes later at a traded minute open. Do not overlap positions or carry a trade across the session.",
            "Use ₹200,000 notional per stock, actual date-aware NSE intraday charges plus 2 bp assumed slippage per side. Evaluate 2024 through 2024-11-30, which is a fixed development sample rather than a future holdout. Run with make cost-aware-ml-intraday.",
        ],
        "configurations": {
            "30-minute cost-aware Random Forest; 2022-2023 train / 2024 evaluation": "nse_cost_aware_30m_random_forest"
        },
    },
)

IDS = frozenset(entry["id"] for entry in ENTRIES)
