# F&O expiry day

*Family: Market events and calendar. Id: `expiry-day`.*

**In one line:** The day derivative contracts settle; volumes and swings near big strikes rise.

**Where you see it:** Options tab (days to expiry); brief Today's map.

**How we compute it:** Expiry dates are in the market calendar (`market_history` expiries); weekly index expiry for one benchmark per exchange since November 2024.

**Data and freshness:** NSE contract specs; bhavcopy.

**Do we hold it:** Yes: expiry dates and option chains.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Option sellers defend strikes with large open interest; pinning near strikes is documented for single stocks on expiry.
- VIX rolls to the next expiries 3 trading days before expiry.

**What it does not tell you:** Direction.

**Traps:**

- Dates and rules change; check NSE before quoting (A-085).
- Expiry-day bhavcopy chains include contracts already settled; ours uses the next expiry by default (HISTORY #31).

**Related:**

- [max-pain](../options/max-pain.md)
- [put-call-ratio](../options/put-call-ratio.md)
- [sebi-fno-rules](../policy/sebi-fno-rules.md)

**Sources:**

- SEBI circular 1 Oct 2024 (search summary); HISTORY #31.

## Example answers

**Q:** Is today expiry?

**A:** Check days to expiry in the options panel; on expiry, open interest and straddle prices behave differently, so compare them with other expiry days only.
