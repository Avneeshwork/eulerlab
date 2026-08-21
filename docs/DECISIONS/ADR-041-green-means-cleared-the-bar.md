# ADR-041 — Green means "cleared the bar", never "performed well"

**Status:** ACCEPTED · 2026-08-21

**Context.** The terminal was rebuilt on the Robinhood reference
(`docs/RESEARCH/018`), which supplies a genuinely good visual grammar:
near-monochrome with one rationed electric accent, a big hero number,
progressive disclosure, structural whitespace. It also supplies one rule that
cannot come along. Robinhood turns the portfolio background green when the
portfolio is up. That mechanic is the most effective thing in their interface,
and it is the exact reflex this platform exists to interrupt: `ARCHITECTURE.md`
§1 opens by explaining that a high backtested Sharpe is usually the luckiest of
N draws. Colour is a faster channel than text — an interface that renders 2.19
in celebratory green has already made the argument before the caveat beside it
is read.

**Options.**
1. Take the grammar including the semantics — green for high returns. Familiar,
   and wrong here.
2. Drop the accent from numbers entirely; monochrome figures only. Safe, and
   throws away the one thing that makes a hundred rows scannable.
3. Keep the grammar, invert the semantics: spend the accent on evidence.

**Choice.** Option 3. `--clear` is applied when a figure is at or above the
noise bar, and to nothing else on the page. A Sharpe of 2.19 selected from forty
unrecorded runs renders in plain ink; a Sharpe of 1.9 that cleared the bar
renders in the accent. The hero number is the bar itself rather than any
strategy's return, for the same reason.

**Why.** The accent is the fastest-read signal in the interface, so it should
carry the one judgement that is actually defensible. "This beat the threshold
that prices selection" is defensible. "This number is large" is not, and is the
claim the rest of the system spends its effort refuting.

**Cost if wrong.** Users may read green as "good" regardless of what it is
attached to, in which case the inversion has bought nothing and may mislead — a
strategy could clear an assumed bar, show green, and be as overfit as any other.
That risk is why the bar is labelled "assumed" wherever it appears. If it proves
unreadable, the honest fallback is Option 2: no colour on numbers at all.
Recorded as an open question in `docs/RESEARCH/018`.
