# ADR-054: The chain tools become explorable

## Status

Accepted, 2026-10-05.

## Context

The options screens showed the newest chain, the whole board, and no way to
interrogate either. Three things were wrong with that.

**679 bhavcopy days are landed and only one was reachable.** The endpoint had
taken a `day` parameter since it was written; the interface simply never sent
one. Every question of the form "what did the skew look like before that
move" was unanswerable from a screen that had the data behind it.

**The whole board is mostly tail.** A NIFTY chain lists 116 to 144 strikes and
the far wings barely trade, so every chart autoscaled to strikes nobody was
looking at and the part with the open interest in it was squeezed into the
middle.

**The charts were pictures.** A smile you cannot read a value off tells you
its shape and nothing else, and shape is the least of what it knows.

## Decision

A day selector over every landed bhavcopy, a strike-range control, and a hover
readout on each chart.

**The range filter is applied once, in the tab, not inside each chart.**
Filtering per chart would let the smile and the gamma profile disagree about
which strikes are on screen — a mismatch nobody notices and everybody
misreads. One `near()` narrows them together.

**Hover finds the nearest point by strike alone, not by euclidean distance.**
Every one of these is a function of strike, so the reader is asking "what is
it *here*" — and a euclidean nearest jumps to a different strike wherever two
series cross, which is exactly where the answer matters most.

**`/api/options/days` is its own endpoint.** The chain endpoint parses a whole
bhavcopy to answer; making it also list 679 dates would charge the cheap
question the price of the expensive one.

## What it immediately showed

The readout earns itself on the first hover. At strike 20,450 on 2026-10-05
the call implies 90.4% and the put 64.6% — a 25.8 point disagreement between
two contracts that parity says should agree. At the money on 2026-09-04 the
same pair agrees to 0.22 points.

That contrast is the whole argument for plotting the legs separately instead
of averaging them into one curve: the gap is a data-quality reading, and a
blended smile throws away the only diagnostic the pair provides.

## Cost if wrong

The range control changes what is displayed and never what is computed — max
pain, the put-call ratio and the arbitrage checks all still run over the full
chain, because narrowing the input to those would change the answers rather
than the view.
