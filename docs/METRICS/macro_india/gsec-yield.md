# 10-year government bond (G-Sec) yield and the yield curve

*Family: Indian economy. Id: `gsec-yield`.*

**In one line:** What the government pays to borrow for ten years; the base rate for valuing every other asset.

**Where you see it:** Brief World section (INDIA 10Y); Dashboard G-Sec line (an index, not the yield).

**How we compute it:** Market yield from the TradingView feed. The dashboard's 'Nifty 10 yr Benchmark G-Sec' is NSE's bond price index, which rises when yields fall.

**Data and freshness:** TradingView at brief time; NSE index history for the price index.

**Do we hold it:** The price index yes (daily); the yield only as a brief-time snapshot.

**What is normal (our data, as of 2026-10-30):** Not computed from our data.

**How to read it:**

- Rising yields lower the present value of future profits, hurting richly valued stocks most, and make bonds a stronger rival to equities.
- A steeper curve (long yields well above short) often signals expected growth or inflation; an inverted curve has preceded slowdowns in other markets.

**What it does not tell you:** RBI's next move on its own.

**Traps:**

- The G-Sec index and the yield move in opposite directions; say which one you mean.
- A change can be quoted in percent of the yield or in basis points.

**Related:**

- [rbi-policy-rate](../macro_india/rbi-policy-rate.md)
- [us-treasury-yield](../macro_global/us-treasury-yield.md)
- [valuation](../market/valuation.md)

**Sources:**

- RBI Weekly Statistical Supplement (FBIL 10-year par yield table; 2021 copy via search).
- `docs/ARCHITECTURE.md` (gsec_note).

## Example answers

**Q:** India 10Y up 15 bp this week. Effect on stocks?

**A:** Higher yields make bonds more attractive and lower the value of distant earnings, so expensive growth stocks and rate-sensitive sectors usually feel it first.
