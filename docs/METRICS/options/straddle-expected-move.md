# ATM straddle and the range to expiry

*Family: Options. Id: `straddle-expected-move`.*

**In one line:** The price of the at-the-money call plus put: roughly the move the market prices in to expiry.

**Where you see it:** Options tab number line; brief Today's map; `options.straddle`, `expected_move`.

**How we compute it:** ATM call + put settlement; low/high = forward ∓ straddle (`market_pulse.expected_move`).

**Data and freshness:** Bhavcopy, nearest expiry.

**What is normal (our data, as of 2026-10-30):** Nifty nearest expiry, 34 sessions held (2026-09-10 to 2026-10-30), so these ranges are thin: straddle median 1.13% of the forward (5th-95th 0.68% to 1.57%), varying with days to expiry.

**How to read it:**

- The straddle covers until expiry, not one day.
- A rough rule is that the straddle is about 0.8 times the one-standard-deviation move to expiry; we show forward ± straddle as the range.

**What it does not tell you:** A guarantee; moves beyond it happen.

**Traps:**

- Compare straddles only at similar days to expiry.
- The brief shows the date of the option data; if it is days old, the range is stale.

**Related:**

- [expected-range](../market/expected-range.md)
- [max-pain](../options/max-pain.md)

**Sources:**

- `market_pulse.expected_move`; the 0.8 rule is the ratio √(2/π) ≈ 0.80 of the normal mean absolute move to its standard deviation.

## Example answers

**Q:** What range do options price for this expiry?

**A:** The ATM straddle is 356 points, so options price Nifty between about 22,352 and 23,064 by the 3 Nov expiry (data of 28 Oct).
