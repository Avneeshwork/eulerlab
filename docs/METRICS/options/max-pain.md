# Max pain

*Family: Options. Id: `max-pain`.*

**In one line:** The expiry settlement that would pay option holders the least, given today's open interest.

**Where you see it:** Options tab; brief Today's map; `options.max_pain`.

**How we compute it:** For each strike as a candidate settlement, total intrinsic value owed on all open calls and puts; the strike with the smallest total (`options/analytics.max_pain`).

**Data and freshness:** F&O bhavcopy, end of day.

**What is normal (our data, as of 2026-10-30):** Not a level with a normal; read it as a distance from spot.

**How to read it:**

- A description of where open interest sits, not a forecast.
- Near expiry, very large OI at one strike can coincide with pinning.

**What it does not tell you:** Where Nifty will settle. The idea that writers steer the index there is unproven.

**Traps:**

- The evidence for pinning is on single US stocks: Ni, Pearson & Poteshman found closes cluster at strikes on expiry days. That is not evidence for index max pain.
- OI changes daily; yesterday's max pain is stale today.

**Related:**

- [put-call-ratio](../options/put-call-ratio.md)
- [straddle-expected-move](../options/straddle-expected-move.md)

**Sources:**

- Ni, Pearson & Poteshman (2005), Journal of Financial Economics 78(1): https://econpapers.repec.org/RePEc:eee:jfinec:v:78:y:2005:i:1:p:49-87 (search summary, 2026-10-31).
- Code docstring in `options/analytics.py`.

## Example answers

**Q:** Max pain is 22,700. Will Nifty go there by expiry?

**A:** Not necessarily. It is the settlement that would cost option buyers most, worked out from today's open interest. Single stocks show some pinning at strikes on expiry day, but nothing shows the index is steered to max pain.
