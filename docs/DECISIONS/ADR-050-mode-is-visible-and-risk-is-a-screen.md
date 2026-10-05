# ADR-050: Mode is visible on every screen, and risk is a screen

## Status

Accepted, 2026-10-05.

## Context

An architecture document for this platform (`Quant_Platform_Architecture.docx`,
5 October 2026) lists eight screens and four design principles. Measured
against it, this console had four of the eight — Overview, Strategies,
Backtests, Data — and neither of the first two design principles:

> Mode is always visible. A paper or live badge sits on every screen, so
> nobody places a real order by mistake.
>
> Risk comes first. Limit usage and the kill switch are on the home screen,
> one click away.

The kill switch was reachable only from a terminal, which in practice means it
was not reachable at the moment anyone would want it.

## Decision

**A mode badge in the top bar, on every screen.** It reads PAPER, and it makes
a stronger claim than a paper/live toggle would: `Stage.LIVE` exists in the
enum and nothing produces it, there is no live broker adapter (S-015), and no
capital has ever been traded. So the badge says `PAPER · no live path` — a
fact about the build, not a setting someone can flip by accident. It polls,
because a kill switch tripped by another process is precisely the state the
interface must not keep quiet about until the next page load. Tripped, it
turns red and replaces the text.

**A Risk screen.** Every limit it shows is read from `config/killswitch.yaml`
through the same loader `oms/killswitch.py` enforces with — not a second copy.
A risk screen showing limits that have drifted from the enforced ones is worse
than no risk screen, because it is believed.

It reports and cannot act. The switch is tripped and reset by a separate
process with separate credentials (a CLAUDE.md hard rule), so a reset button
here would be lying about who can act; the screen says so in words instead.

## What was deliberately not built

The document also lists **Orders**, **Logs** and **Models**.

Orders and Logs have real data behind them — the write-ahead journal and the
order book — and are worth building; they were left out of this change for
size, not for doubt.

**Models was not built and should not be, yet.** There is no model registry on
this platform: `master/registry.py` is the instrument registry. There are no
model versions, no validation records and no promotion path, so a Models
screen would be a page about nothing, and an empty screen in a console reads
as "no models yet" rather than "this does not exist" — which is the kind of
quiet misstatement this project treats as a defect. The registry comes first;
the screen follows it.

## Cost if wrong

The badge is cheap to change. The Risk screen's one real risk is drift, and it
is structurally prevented: it reads the enforced file through the enforcing
loader, so the only way for it to show a wrong limit is for the order path to
enforce the same wrong limit.
