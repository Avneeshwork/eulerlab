# METRICS — what every number on the platform means, and how to talk about it

One page per metric. Each says what the metric is, how this codebase computes it (with the
file), what is normal on our own data, how to read it, what it does not tell you, its traps,
its sources, and example answers. The rules for answering are in
[HOW_TO_ANSWER.md](HOW_TO_ANSWER.md). The maths lives in `docs/ARCHITECTURE.md`; these pages
point to it rather than repeat it. Built for the assistant, the brief and the knowledge agent
(ADR-103), and for the operator.

To read it as one searchable page, run `make handbook` and open
`http://localhost:3000/handbook.html` in the workbench.

"What is normal" figures were computed from the data held on 2026-10-30. They age: the
percentile a payload carries (for example `percentile_1y`) is always the live answer.

## Market context

| Metric | In one line |
|---|---|
| [Index level and returns (1 day to 1 year)](market/index-returns.md) | Where an index closed and how far it moved over 1, 5, 21, 63 and 252 sessions. |
| [India VIX and its percentile](market/india-vix.md) | The market's own 30-day forecast of Nifty volatility, from option prices, ranked against the past year. |
| [One-day range from VIX](market/expected-range.md) | The band Nifty would stay inside on about two days in three if VIX were right. |
| [Breadth: share of stocks above their 20, 50 and 200-day averages](market/breadth-above-average.md) | How many NSE stocks are in their own uptrend, rather than what the index did. |
| [New 52-week highs and lows](market/new-highs-lows.md) | How many stocks closed at a one-year high or low today. |
| [High-Low Index](market/high-low-index.md) | The 10-day average share of new highs among new highs plus new lows, 0 to 100. |
| [Sector relative strength and phase](market/sector-relative-strength.md) | Which sectors beat or lag Nifty 50, and whether that is improving. |
| [Index valuation: P/E, P/B and dividend yield](market/valuation.md) | How expensive Nifty is against its own history, from NSE's published ratios. |
| [F&O positioning: index futures long share by FII, DII, Pro, Client](market/participant-long-share.md) | What share of each group's index-futures contracts are long, against what is usual for that group. |
| [FII/DII cash-market flows](market/fii-dii-cash-flows.md) | Rupees foreign and domestic institutions bought minus sold in the cash market, per day. |
| [Delivery percentage and delivery spikes](market/delivery-percent.md) | Share of a stock's traded shares that were delivered rather than squared off the same day. |
| [Trend card (Faber's 10-month rule)](market/pulse-trend.md) | Uptrend if Nifty's last month-end close is above the average of the last 10 month-ends, else Downtrend. |
| [Participation card](market/pulse-participation.md) | Broad, Mixed or Narrow from the 200-day breadth share and the High-Low Index. |
| [Fear card](market/pulse-fear.md) | Elevated, Normal or Calm from India VIX's one-year percentile. |
| [Big money card](market/pulse-big-money.md) | FII index-futures long share against its own year: more bearish, usual or more bullish than usual. |
| [World markets: crude, gold, dollar, yields, rupee](market/world-markets.md) | Overnight moves in the global prices that feed Indian markets. |

## Options

| Metric | In one line |
|---|---|
| [Put-call ratio (PCR) by open interest](options/put-call-ratio.md) | Open put contracts divided by open call contracts on Nifty's nearest expiry. |
| [Max pain](options/max-pain.md) | The expiry settlement that would pay option holders the least, given today's open interest. |
| [At-the-money implied volatility (ATM IV)](options/atm-implied-volatility.md) | The volatility the market prices into Nifty's nearest at-the-money options. |
| [Implied volatility (any strike)](options/implied-volatility.md) | The volatility that makes the Black-76 price equal the option's market price. |
| [ATM straddle and the range to expiry](options/straddle-expected-move.md) | The price of the at-the-money call plus put: roughly the move the market prices in to expiry. |
| [Option greeks: delta, gamma, theta, vega](options/greeks.md) | How an option's price changes with the index, with time, and with volatility. |
| [Gamma exposure (GEX) by strike](options/gamma-exposure.md) | Gamma times open interest per strike, signed on an assumption about who holds the options. |
| [Volatility smile and skew](options/volatility-smile.md) | Implied volatility across strikes for one expiry. |

## Strategy performance

| Metric | In one line |
|---|---|
| [Sharpe ratio](performance/sharpe-ratio.md) | Average daily return divided by its standard deviation, scaled to a year. |
| [Sortino ratio](performance/sortino-ratio.md) | Like Sharpe, but only losing days count as risk. |
| [Total return and annualised return (CAGR)](performance/total-and-annual-return.md) | How much the money grew over the test, and the same as a yearly compound rate. |
| [Time-weighted return (live and paper books)](performance/time-weighted-return.md) | Growth of the book with deposits and withdrawals taken out. |
| [Volatility (annualised)](performance/volatility.md) | Standard deviation of daily returns scaled to a year. |
| [Maximum drawdown, and time to trough and recovery](performance/max-drawdown.md) | The largest fall from a previous high, and how long it took to fall and to recover. |
| [Hit rate (daily) and win rate (per trade)](performance/hit-rate.md) | Share of up days, or share of closed trades that made money. |
| [Profit factor and expectancy](performance/profit-factor.md) | Gross profit divided by gross loss over closed trades, and the average net per trade. |
| [Turnover, cost drag and slippage](performance/turnover-and-costs.md) | How much was traded relative to capital, and how much the charges ate. |
| [Invested fraction and exposure](performance/invested-fraction.md) | Share of days (or capital) actually in the market. |
| [Capacity: days to trade](performance/capacity.md) | How many days each buy would take at a set share of the stock's daily turnover, and the capital that fits in one day. |
| [Beta and alpha (factor regression)](performance/beta-and-alpha.md) | How much of the return moved with the market and factors, and what was left over. |
| [Skew and excess kurtosis](performance/skew-and-kurtosis.md) | Whether returns lean to big losses or big gains, and how fat the tails are. |
| [Benchmark comparison (Nifty return over the same window)](performance/benchmark-return.md) | What Nifty did over exactly the strategy's test window. |
| [Sharpe without the best year, and best 1% of days](performance/sharpe-without-best-year.md) | Whether the result depends on one lucky year or a handful of days. |

## Validation and the gate

| Metric | In one line |
|---|---|
| [Trial count (the ledger)](validation/trial-count.md) | How many strategy configurations have been evaluated; every statistic below depends on it. |
| [Noise bar (expected maximum Sharpe of N worthless strategies)](validation/noise-bar.md) | The Sharpe the best of N pure-noise strategies would show; the bar a real one must beat. |
| [Deflated Sharpe ratio (DSR)](validation/deflated-sharpe.md) | Probability that the true Sharpe is above zero, after counting how many things were tried. |
| [t-statistic of the strategy's mean return](validation/t-statistic.md) | How many standard errors the average return is from zero. |
| [Minimum backtest length (MinBTL)](validation/min-backtest-length.md) | Years of history needed before a target Sharpe can be told apart from luck, given N trials. |
| [Probability of backtest overfitting (PBO)](validation/pbo.md) | How often the configuration that won in sample finishes below the median out of sample. |
| [Combinatorial purged cross-validation (CPCV)](validation/cpcv.md) | Fifteen train/test splits over time with leaks removed, instead of one. |
| [Stress tests: 2× costs, drop best names, worst regime, delay](validation/stress-tests.md) | Share of Sharpe that survives when conditions get worse. |
| [Monte Carlo: shuffled drawdowns and bootstrapped Sharpe](validation/monte-carlo-drawdown.md) | How bad the drawdown could have been with the same returns in another order, and how uncertain the Sharpe is. |
| [Information coefficient (IC) and its t-statistic](validation/information-coefficient.md) | Rank correlation between a feature today and returns that followed, averaged over dates. |
| [Gate verdict and the holdout](validation/gate-verdict.md) | PROMOTE or KILL from every check above; then one read of the held-back data. |

## Risk on the live book

| Metric | In one line |
|---|---|
| [Value at risk (VaR), 95% and 99%](risk/value-at-risk.md) | A one-day loss today's holdings would have exceeded on only 5% (or 1%) of the last 250 days. |
| [Expected shortfall](risk/expected-shortfall.md) | The average loss on the days beyond VaR. |
| [Recent-weighted (EWMA) VaR](risk/ewma-var.md) | VaR from a volatility that weights recent days more, so it reacts faster. |
| [Component VaR and VaR without a book](risk/component-var.md) | Each deployment's share of the book's VaR, and the book's VaR if it were removed. |
| [Correlation between books](risk/correlation.md) | How closely two deployments' daily P&L moved together. |
| [Book beta and market-fall stress](risk/book-beta-and-stress.md) | How much the book moves per 1% Nifty move, and its loss in a set market fall. |
| [Concentration and sector share](risk/concentration.md) | How much of the money sits in the largest names and the largest sector. |
| [Loss limits: reduce-only and halt](risk/loss-limits.md) | A deployment's drawdown from its own high against the levels that change what it may do. |
| [Live against the backtest band](risk/backtest-band.md) | Whether the live book's return so far sits inside the range its backtest produced over the same horizon. |
| [Overnight gap rule VaR](risk/overnight-gap-var.md) | Risk of a position held only overnight, from past morning gaps on nights it would have held. |

## Attribution

| Metric | In one line |
|---|---|
| [Brinson attribution: allocation, selection, interaction](attribution/brinson-attribution.md) | How much of the gap to the benchmark came from sector weights versus stock picks. |
| [Factor exposures and rolling exposure](attribution/factor-exposure.md) | How much the strategy behaves like the market, small caps, momentum or low volatility. |

## Data quality

| Metric | In one line |
|---|---|
| [Data grade (A to D)](quality/data-grade.md) | How far a dataset passes the quality contract: registered, provenance, fingerprint, sense, quarantine. |
| [Freshness (ok, behind, stale, missing)](quality/freshness.md) | Whether a dataset's last date is where it should be by now. |
| [Point in time (event time and knowledge time)](quality/point-in-time.md) | Every record says when it happened and when we knew it, so research never sees the future. |

## Company fundamentals

| Metric | In one line |
|---|---|
| [Company P/E and industry median P/E](fundamentals/company-pe.md) | Price over trailing earnings per share, against the median of profitable peers. |
| [ROCE and ROE](fundamentals/returns-on-capital.md) | Profit earned on the capital the business uses, and on shareholders' equity. |
| [Margins and growth](fundamentals/margins-and-growth.md) | Profit as a share of sales, and how fast sales and profit grow. |
| [Debt to equity](fundamentals/debt-to-equity.md) | Borrowings against shareholders' funds. |
| [Fair-value estimate (residual income)](fundamentals/fair-value-estimate.md) | An internal estimate of value from book value, earnings, peers and the cost of equity. |

## Indian economy

| Metric | In one line |
|---|---|
| [RBI repo rate and the monetary policy decision](macro_india/rbi-policy-rate.md) | The rate at which RBI lends to banks overnight; the main lever on borrowing costs in India. |
| [Banking system liquidity (LAF balance)](macro_india/rbi-liquidity.md) | Whether banks have surplus cash parked with RBI or are short and borrowing from it. |
| [CPI inflation (retail)](macro_india/cpi-inflation.md) | Year-on-year change in consumer prices; the inflation measure RBI targets. |
| [WPI inflation (wholesale)](macro_india/wpi-inflation.md) | Year-on-year change in wholesale prices; a read on input costs for companies. |
| [GDP growth](macro_india/gdp-growth.md) | Quarterly growth of the economy's output. |
| [Index of Industrial Production (IIP)](macro_india/iip.md) | Monthly growth in factory, mining and electricity output. |
| [PMI (manufacturing, services, composite)](macro_india/pmi.md) | A monthly survey of purchasing managers; above 50 means activity expanded on the month. |
| [10-year government bond (G-Sec) yield and the yield curve](macro_india/gsec-yield.md) | What the government pays to borrow for ten years; the base rate for valuing every other asset. |
| [Rupee (USD/INR) and forex reserves](macro_india/rupee.md) | How many rupees one dollar buys, and RBI's stock of foreign currency to defend it. |
| [Fiscal deficit, current account deficit and trade balance](macro_india/fiscal-and-current-account.md) | How much the government borrows, and how much more India imports than it earns abroad. |
| [GST collections](macro_india/gst-collections.md) | Monthly goods and services tax revenue; a quick read on consumption and compliance. |

## Global economy and markets

| Metric | In one line |
|---|---|
| [US Federal Reserve (FOMC) rate decisions](macro_global/us-fed.md) | The US policy rate; the single biggest driver of global money moving into or out of emerging markets. |
| [US inflation and jobs data (CPI, payrolls)](macro_global/us-data.md) | The US numbers that move Fed expectations, and so global markets. |
| [US 10-year Treasury yield](macro_global/us-treasury-yield.md) | The world's benchmark risk-free rate. |
| [Dollar index (DXY)](macro_global/dollar-index.md) | The dollar against six major currencies. |
| [Crude oil (Brent, WTI)](macro_global/crude-oil.md) | The price of oil; India imports most of what it uses. |
| [Gold](macro_global/gold.md) | The traditional safe asset; also a large Indian import. |
| [GIFT Nifty and overnight global markets](macro_global/gift-nifty.md) | Nifty 50 futures traded in GIFT City before India opens; the first read on the morning. |
| [Other central banks: ECB, Bank of Japan, People's Bank of China](macro_global/global-central-banks.md) | Policy moves elsewhere that shift global liquidity and currencies. |

## Government policy and regulators

| Metric | In one line |
|---|---|
| [Union Budget](policy/union-budget.md) | The government's yearly plan for spending, borrowing and taxes, usually presented on 1 February. |
| [Capital gains tax and securities transaction tax (STT)](policy/capital-gains-and-stt.md) | The taxes on investment profits and on each trade. |
| [SEBI's index derivatives rules (2024 framework)](policy/sebi-fno-rules.md) | The rules SEBI tightened in 2024 to curb speculative index F&O trading. |
| [Foreign portfolio investor (FPI) rules](policy/fpi-rules.md) | Who may invest from abroad, in what category, and with what limits. |
| [GST Council decisions](policy/gst-council.md) | Changes to indirect tax rates on goods and services. |
| [Government schemes, PLI and disinvestment](policy/government-schemes-and-disinvestment.md) | Policies that direct money to sectors, and government stake sales in listed companies. |
| [Elections](policy/elections.md) | National and major state elections and their results. |

## Institutions and money flows

| Metric | In one line |
|---|---|
| [RBI and SEBI: who regulates what](institutions/rbi-and-sebi.md) | RBI runs monetary policy, banks and the rupee; SEBI regulates markets, brokers, funds and listed companies. |
| [FIIs / FPIs: foreign investors](institutions/fii-fpi.md) | Foreign funds, pension funds and sovereign investors buying Indian securities. |
| [DIIs: mutual funds, insurers, pension funds, banks](institutions/dii-mutual-funds-insurers.md) | Domestic institutions; mostly mutual funds investing monthly SIP money, plus LIC and other insurers. |
| [SIP flows and mutual fund inflows (AMFI)](institutions/sip-flows.md) | Monthly money retail investors put into mutual funds through systematic plans. |
| [Big banks and financials in the index](institutions/big-banks.md) | Banks and financial companies are among the heaviest sectors in Nifty 50, so their results and RBI's rules move the index. |
| [MSCI, FTSE and passive funds](institutions/global-index-providers.md) | Global index weights decide how much passive money must buy or sell Indian stocks. |

## Market events and calendar

| Metric | In one line |
|---|---|
| [F&O expiry day](events/expiry-day.md) | The day derivative contracts settle; volumes and swings near big strikes rise. |
| [Index rebalancing (Nifty) and index inclusion](events/index-rebalancing.md) | Stocks entering or leaving an index, which forces index funds to buy or sell them. |
| [Index inclusion effects (stocks)](events/index-inclusion.md) | The price effect on a stock of being added to or removed from a major index. |
| [Quarterly results season](events/results-season.md) | The weeks when listed companies report quarterly earnings. |
| [New supply: IPOs, OFS, QIPs and lock-in expiries](events/supply-ipos-ofs-qip.md) | Fresh shares coming to market, which absorb money that might otherwise buy existing stocks. |
| [Block and bulk deals; insider (SAST) disclosures; pledges](events/block-and-bulk-deals.md) | Large trades by named parties, and promoters' buying, selling or pledging. |
| [Corporate actions: dividends, splits, bonuses, rights](events/corporate-actions.md) | Company events that change the share count or pay out cash, and so the price. |

## Market structure and trading rules

| Metric | In one line |
|---|---|
| [Trading sessions: pre-open, normal, closing](structure/trading-sessions.md) | How the trading day is organised on NSE. |
| [Circuit breakers and price bands](structure/circuit-breakers.md) | Market-wide halts at 10%, 15% and 20% index moves, and per-stock daily price limits. |
| [Settlement (T+1)](structure/settlement.md) | When shares and money actually change hands after a trade. |
| [F&O ban period and market-wide position limit (MWPL)](structure/fno-ban.md) | A stock's derivatives are frozen to new positions once open interest passes 95% of its limit. |
| [Margins: SPAN, exposure, peak margin](structure/margins.md) | The money brokers must collect before you can hold a position. |
| [Lot size, tick size and contract multiplier](structure/lot-size-and-tick.md) | The units contracts trade in; they change over time. |
| [Margin trading (MTF) and securities lending (SLBM)](structure/mtf-and-slbm.md) | Borrowed money used to buy shares, and shares lent out for short selling. |
