# What history says (base rates for today's setup)

*Family: Market context. Id: `history-base-rates`.*

**In one line:** Past days that looked like today on three fixed conditions, and what Nifty did over the next 1, 5 and 20 sessions.

**Where you see it:** Market brief and markets-closed note, section What history says; `data.brief.history`.

**How we compute it:** A past day matches when Nifty's side of its 200-day average, India VIX's band against its previous 251 closes (under 30th, 30th-70th, 70th up) and who leads over 21 sessions (large minus small cap return beyond ±3 points) all read as today. For each horizon: median return, share up, worst 10% (10th percentile), matching days and episodes (`agents/history_says.py`, `config/history_setup.yaml`).

**Data and freshness:** Index history since 2015 (Nifty 50, India VIX, Nifty Smallcap 250).

**Do we hold it:** Yes.

**What is normal (our data, as of 2026-10-30):** On 2026-10-30 the setup (below the 200-day, VIX high, large caps leading) matched 123 days in 21 episodes since 2016-04-01; next 5 sessions median +1.52%, up 68% of the time, worst 10% -2.21% or lower.

**How to read it:**

- It is the outside view: how often days like this were followed by gains, and how bad the bad cases were.
- Read the episodes count with the days: 123 days in 21 episodes is closer to 21 independent cases than 123.

**What it does not tell you:** What will happen this time. It is history, not a forecast, and it has passed no gate.

**Traps:**

- Under 30 matching days the brief gives no numbers; it says too few.
- Changing the conditions until the history looks good would be a search with no trial count. They are fixed in config and must not be tuned to results (A-087).
- Overlapping horizons: consecutive matching days share most of their 20-session window.

**Related:**

- [india-vix](../market/india-vix.md)
- [pulse-trend](../market/pulse-trend.md)
- [index-returns](../market/index-returns.md)
- [books-in-this-market](../performance/books-in-this-market.md)

**Sources:**

- Lovallo & Kahneman on the outside view; SentimenTrader's precedent studies (research 134).
- ADR-106.

## Example answers

**Q:** What usually happens after days like today?

**A:** Since 2016 there were 123 days with Nifty below its 200-day average, VIX in its top 30% and large caps leading, in 21 separate episodes. Over the next 5 sessions Nifty's median was +1.5%, up 68% of the time, but the worst 10% lost 2.2% or more. That is history, not a forecast.
