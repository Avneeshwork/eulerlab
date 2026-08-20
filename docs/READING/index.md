# READING — what to read, and when, and why

Three tiers only:

- **MUST** — without this you cannot tell whether the next sprint's work is
  correct. It blocks your ability to verify.
- **SHOULD** — this month. Makes the reviews make sense.
- **LATER** — before a specific sprint that is still far off.

Every entry says *why it matters for the decision you are about to make*. This
is not a textbook list. Total MUST reading across sprints 1–4 is about
2.5 hours.

No URLs are given where I have not verified one. Where a source is named without
a link, it is a book or paper you will find by title; where a free alternative
exists I have said so.

---

## MUST — before Sprint 4 (approving the lookahead firewall)

### Lookahead and survivorship bias — 60 min

**Why:** Sprint 4 builds the firewall that makes these two failures structurally
impossible, and ships ~15 adversarial tests that actively try to leak the future.
Your job at that review is to judge whether the test suite tests the *right*
thing. You cannot do that without knowing what the attacks look like.

**Source:** López de Prado, *Advances in Financial Machine Learning*, chapters
1–3. If you would rather not buy a book yet, any careful treatment of backtest
bias covers the same ground — the concepts matter, not the author.

**Test yourself:** can you explain why running a strategy on today's Nifty 50
constituent list against 2015 data inflates returns, and roughly by how much the
playbook says that class of error is worth? (Playbook §1.2: "often worth several
points of fake annual return".)

**Second test:** a colleague computes a 20-day moving average and compares it to
today's close to generate a signal. What is wrong, and what would make it right?

---

## SHOULD — this month

### Idempotency, and why raw data is immutable — 20 min · needed for Sprint 1

**Why:** Sprint 1's acceptance test is that you run `make ingest-eod` twice and
the second run downloads **nothing**. That is the whole idea of idempotency. The
related rule — the landing zone is never edited, never deleted — is what lets us
rebuild everything after a bug is found in the processing code. And one will be.

**Source:** no reading needed beyond `docs/GLOSSARY.md`. The concept is one
paragraph; the discipline is the hard part.

**Test yourself:** the downloader crashes halfway through 2015. You restart it.
What must happen to the files it already wrote, and why must it not re-download
them?

### Point-in-time data, and why symbols are never join keys — 30 min · needed for Sprint 3

**Why:** Sprint 3 builds the security master, and its acceptance test is that you
can ask "what was the Nifty lot size on this date in 2023" and get the right
answer. Every field is time-versioned for that reason. Separately, symbols
change — Zomato became Eternal — so joining on a ticker silently corrupts
history at the rename date.

**Source:** playbook §1.1 and §1.2 (you already have it, ~15 minutes of reading).

**Test yourself:** why is an internal integer ID a safer join key than an ISIN,
which is supposed to be permanent?

---

## LATER

| Topic | Time | Needed before |
|---|---|---|
| Ratio vs difference adjustment for futures continuation series | 30 min | Sprint 5 — the choice can flip the sign of a trend strategy's backtest |
| Robust statistics: why median absolute deviation, not standard deviation | 20 min | Sprint 6 — stdev is broken by the very outliers you are hunting |
| No-arbitrage bounds on option prices; Black-76 vs Black-Scholes | 45 min | Sprint 7 — why Indian index options use the futures variant |
| Information Coefficient and factor neutralisation | 40 min | Sprint 8 — IC screening is 50× cheaper than backtesting, so it is the mandatory first filter |
| Indian transaction taxes; the square-root market impact law | 45 min | Sprint 9 — `make check-costs` must reproduce your real contract notes to the paisa |
| Event-driven vs vectorised architecture | 30 min | Sprint 11 |
| Property-based testing | 30 min | Sprint 12 — the most important gate in the project |
| CPCV, Deflated Sharpe Ratio, PBO | 90 min | Sprint 13. **This is the second MUST**, and the heaviest single item in the list |
| Multiple testing and the t > 3 rule | 30 min | Sprint 14 |
| SPAN margin mechanics | 45 min | Sprint 13+ |
| Idempotency and order state machines | 45 min | Sprint 19 — before anything can place an order |

---

## Nothing to read for Sprint 2

Sprint 2 is the options chain recorder. It needs a VPS and a data source
decision, not reading. Every day it is not running is a day of option-chain
history that cannot be bought back at any price.

## MUST READ before Sprints 29–31 (going live)

- **Idempotency and deterministic identifiers** — 20 min
  Why: Sprints 19–28 make a retry safe by deriving the order id from what the
  order *means* rather than from a counter. You need to be able to say why that
  works, because it is the property that stops a network hiccup from
  double-sending real money.
  Test yourself: why does re-running the same rebalance twice place no second
  order, and what would break that?

- **Order state machines, and why a timeout is neither success nor failure** —
  25 min
  Why: the single most important idea in the order path. A send has three
  outcomes, not two, and both two-outcome readings cost money in opposite
  directions.
  Test yourself: your broker times out on a buy. Name the cost of assuming it
  failed, and the cost of assuming it worked.

## SHOULD READ this month

- **Implementation shortfall** — 30 min
  Why: `make attribution` is a simplified form of it. Right now it decomposes
  paper against backtest, where both books are ours and the residual is an
  identity. Once a real broker is on the other side, the same report becomes a
  real measurement, and you will want to know what the components mean.

- **Write-ahead logging** — 20 min
  Why: explains why the order journal writes and fsyncs the *intent* before
  talking to the broker, and why reversing those two lines is the one change
  that makes a crash unrecoverable.
