# ADR-071 — Risk on the deployed book is measured from today's holdings, and the screen only warns

**Context.** Operator, 2026-10-14: "a screen which shows risk on current
trading strategies: current VaR, strategy distribution, maximum risk,
allocation in different strategies", then "start building all" after the
mockup of research 079. Each deployment was shown alone, and the only risk
figures on the platform were the kill switch's counts and rupee limits.

**Options.** For the risk numbers: (a) from each deployment's own daily
returns; (b) from today's holdings run through past prices; (c) from the
strategy's backtest returns. For limits: (x) new limits that stop or reduce
trading; (y) levels that only warn.

**Choice.** (b) and (y). `risk/book.py` applies each of the last 250 trading
days' returns to today's rupee value in every name held, which gives a
profit-and-loss history for the book as it stands. One-day VaR at 95% and 99%
and expected shortfall are read from it three ways: the history itself
(nearest rank), a normal curve, and a normal curve whose spread weights
recent days by 0.94 a day (A-059). The book's VaR is split between
deployments by covariance with the book, so the parts sum to the whole.
Stress moves each name by a stated shock, through its own beta to NIFTYBEES
for a market fall, and a name with no measured beta is given a beta of 1.
`/api/risk/book` serves it; Live & Risk has three new views: Risk overview,
Performance, Stress & exposure. `config/risk_watch.yaml` holds four warning
levels (book VaR 2%, book drawdown 10%, deployment drawdown 8%, largest
sector 35%); they colour a row and do nothing else.

**Why.** (a) is not a number: the deployments are 3 to 7 days old. (c)
describes the strategy over ten years, not the nine names it holds today.
(b) answers the question asked, "what could this book lose tomorrow", from
prices already held, with no new data. Limits that act belong to the kill
switch, which is a separate process with its own credentials and
operator-owned values; a screen that could stop trading would be a second,
weaker switch. Fewer than 60 days of prices gives no VaR at all instead of a
small-sample one.

**Cost if wrong.** The figures see only what is held at the close. The
overnight futures deployment holds nothing then, so 95% of today's money
shows no risk; every view says so at the top. A name with no price on a past
day counts as flat that day, which understates risk for a new listing; the
payload reports how much of the book that is. Closes say nothing about
liquidity, so a real loss in small names can be worse. The watch levels were
proposed with the screen and measured against nothing: they are the
operator's to change. The backtest band uses overlapping stretches of the
backtest, so it is smoother than the evidence deserves, and no verdict is
given before 20 days live.
