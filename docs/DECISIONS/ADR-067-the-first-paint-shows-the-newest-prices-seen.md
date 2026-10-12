# ADR-067 — The dashboard's first paint shows the newest prices already seen

**Context.** Operator, 2026-10-12: "in dashboard it get last day data initially
instead of last minute bar data and then get live". The first paint answers
from held data so it does not wait on a broker (0.4 s against 6 to 9). Held
data meant the daily panel, so on a Monday afternoon the screen opened on
Friday's moves and jumped to today's a second later. The held minute bars were
no newer: the nightly job fetches them with the panel, and they cover 422 of
about 2,350 stocks.

**Options.** (a) Read held minute bars on the first paint. (b) Save the last
live quotes to one file and show those first. (c) Both, the newer laid over
the older. (d) Leave it and reword the label.

**Choice.** (c), chosen by the operator from (a), (c) and (d):
`eulerlab/last_seen.py`. A live snapshot that priced the universe without an
error writes its quotes to `data/derived/last_seen_quotes.json`, replaced
whole. The first paint lays over the panel whatever postdates the panel's last
day, and the screen says "last seen" with the time.

**Why.** (a) alone changes nothing on most days. (b) covers every stock the
broker prices and costs 2 ms to read. Keeping (a) as a layer costs 40 ms and
is right on a day the minute feed ran in the session. Anything dated on or
before the panel's last day is ignored, so a stale file cannot hide a settled
close.

**Cost if wrong.** The screen opens on prices that are minutes or days old.
They are labelled with their time and replaced by the live answer within
seconds; no study, order or stored result reads this file.
