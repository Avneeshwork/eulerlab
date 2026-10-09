# ADR-062 — The price panel and the paper books follow the data by themselves

**Context.** Operator, 2026-10-09: "price panel and paper trading should auto
update on data change". They moved only when a run named them, so data landed
any other way left them behind (T-4030).

**Options.** (a) A launchd job every few minutes. (b) A file watcher library.
(c) `daily_feed.DEPENDENTS` pulls them into any run that fetches NSE files, plus
a thread in the API server that checks every 5 minutes (`deploy/autoupdate.py`).

**Choice.** (c). Each check reads the NSE manifest's latest cash day and the
panel's last line; it builds the panel or replays a paper book only when one is
behind, and stands aside while the `feed` lock is held. `EULERLAB_AUTOUPDATE=0`
turns the thread off.

**Why.** No new dependency or scheduler, and the check costs milliseconds. The
API runs whenever the operator is watching; `make daily` covers the rest.

**Cost if wrong.** With the API stopped and no `make daily`, nothing catches up
until one of them runs. A paper book replays at most once per panel change.
