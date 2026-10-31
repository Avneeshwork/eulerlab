# Trend card (Faber's 10-month rule)

*Family: Market context. Id: `pulse-trend`.*

**In one line:** Uptrend if Nifty's last month-end close is above the average of the last 10 month-ends, else Downtrend.

**Where you see it:** Dashboard pulse; brief scorecard row Trend.

**How we compute it:** `market_pulse.trend_card`; badge from the fall off the 252-day high: Correction 10-20%, Bear market 20%+.

**Data and freshness:** Index history; changes only at a month's end.

**What is normal (our data, as of 2026-10-30):** On 2016-2026 Nifty it changed about 2 times a year (research 122).

**How to read it:**

- Slow by design. Faber's tests show it mainly avoided deep bear markets.
- The brief also reads Nifty against its 50 and 200-day averages, which move faster.

**What it does not tell you:** Short-term direction.

**Traps:**

- Tested on US data from 1900; India evidence is thin (A-063).

**Related:**

- [index-returns](../market/index-returns.md)
- [breadth-above-average](../market/breadth-above-average.md)

**Sources:**

- Faber (2007), Journal of Wealth Management, via research 122.
- Brock, Lakonishok & LeBaron (1992): https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html.

## Example answers

**Q:** Trend says Downtrend but Nifty rose this week?

**A:** The trend rule only reads month-end closes against a 10-month average, so it changes about twice a year. A good week does not move it; a month-end close above the average would.
