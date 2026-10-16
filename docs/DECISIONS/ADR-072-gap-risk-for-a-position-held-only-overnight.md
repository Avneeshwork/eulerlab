# ADR-072 — A position held only overnight is in the risk figures as it is run, with its own "night it holds" VaR

**Context.** Operator, 2026-10-14: "include gap risk in futures position, it
should also have VaR, and how will you manage new strategy addition or
removal". The overnight deployment buys a Nifty future at the close on a
signal day and sells at the next open. Its book is empty at every close, so
ADR-071's figures, which read holdings, showed 95% of the money carrying no
risk at all.

**Options.** For the future: (a) leave it out and say so; (b) count it only
on nights it holds, so the book's VaR jumps between two regimes; (c) count it
as it is run, the gap on signal nights and nothing otherwise, and state the
risk of a night in position beside it. For adding and removing: (x) a list of
deployments the risk code is told about; (y) read whatever is deployed.

**Choice.** (c) and (y). `risk.book.GapRule` carries the near contract, the
lots today's equity buys, every morning's gap (open over the previous close)
and the mornings the rule had been in position. Its daily series is
`notional * gap` on those mornings, else zero, dated to the morning so it
lines up with the shares' close-to-close day. That series joins the book's,
so the future is in the book VaR, component VaR, correlation and beta. Beside
it: VaR and expected shortfall over the signal nights alone, the worst such
night in the window, and the worst gap in the whole futures history at
today's size. Two stress rows are added (the future opens 3% lower; its worst
gap on record) and one limit row sets a 1-in-20 night against the kill
switch's daily loss.

A deployment is in the figures by being active; nothing registers it. One
that is stopped leaves every figure and is listed with what it made. Each
deployment's colour is its place in the order they were created, stopped ones
included, so the rest do not change colour. Each row shows the book's VaR
without it. `POST /api/risk/what-if` gives the book's VaR before and after
adding a strategy at a given capital, and the Deploy dialog shows it.

**Why.** (a) hid the largest risk on the book. (b) is the right answer to
"what can I lose tonight" but makes every other figure on the page mean
something different from one day to the next. (c) keeps one meaning for the
book's VaR and puts tonight's question in its own figure, labelled. A
registry of deployments (x) is a second list to keep in step with the first.

**Cost if wrong.** The book's VaR averages quiet nights with signal nights:
on a signal night it understates. The page says so and gives the other
figure. A gap cannot be stopped out, so these are losses taken in full; the
kill switch acts only after the open. The 78 signal nights of the last year
are a small sample for a 95% tail (four nights). The what-if sizes a new
share strategy as equal amounts of the names it would hold today (A-060),
which is close for an equal-weighted strategy and wrong for any other.
