# 197 — What does LIQUIDBEES earn, and where can a backtest get it?

**Question.** LIQUIDBEES' price stays at ₹1,000 (HISTORY #97). What return series should a backtest holding it use for 2003-2024?

**Sources (fetched 2026-11-15).**
- Nippon India AMC scheme page, https://mf.nipponindiaim.com/FundsAndPerformance/Pages/NipponIndia-ETF-Nifty-1D-Rate-Liquid-BeES.aspx — invests in tri-party repo on G-Sec or T-bills, repo and reverse repo; benchmark Nifty 1D Rate Index; daily dividend with compulsory reinvestment. No TER on the page.
- IIMA Indian Fama-French and Momentum data library FAQ, https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/FAQ.php — the risk-free return is from annualised yields of new 91-day T-bill issues, provided by the RBI. Daily file landed 2026-10-21 (`data/landing/india_factors/iima_daily_survivorship_adjusted/2025/12/2025-12-31_csv.csv`, URL in its manifest row).
- RBI Handbook of Statistics, Table 176 (https://rbi.org.in/Scripts/PublicationsView.aspx?id=22650) and Table 183 (id=17958): monthly weighted call money rates, 2011-12 onward only per edition; older editions' PDFs were behind a human-verification page and were not read.
- TER: aggregator pages (TradingView, PL India, INDmoney, ICICI Direct: 0.69%; Choice India, Equirus: 0.65%; Value Research: 0.59%; Groww, Sharpely: 0.71% for the daily IDCW plan). No AMC factsheet was read.

**Findings.**
1. No daily dividend record of LIQUIDBEES for 2003-2024 was found in a fetchable primary source.
2. IIMA's daily RF is in percent per trading-day interval (a Monday carries the weekend). Compounded by calendar year it reads 4.93% (2003), 7.75% (2008), 3.72% (2009), 8.62% (2013), 3.38% (2021), 6.80% (2024), in line with the 91-day T-bill.
3. LIQUIDBEES holds overnight repo, not T-bills; overnight and 91-day rates differ by tens of basis points, more in stress (2008, 2013).

**Decision.** Total return = IIMA daily RF less a 0.69% a year fee (A-157), `features.panel.with_cash_yield`, research runs only (ADR-204).

**Confidence.** Medium: the level is right to within about 0.5-1% a year; the day-to-day path is the T-bill's, not the overnight rate's.

**Open.** A daily overnight series (FBIL/NSE MIBOR or RBI's daily call rate) back to 2003, and the AMC's TER history, would replace the proxy.
