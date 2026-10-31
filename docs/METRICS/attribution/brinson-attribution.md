# Brinson attribution: allocation, selection, interaction

*Family: Attribution. Id: `brinson-attribution`.*

**In one line:** How much of the gap to the benchmark came from sector weights versus stock picks.

**Where you see it:** Strategy report → attribution.

**How we compute it:** Brinson-Fachler by sector each month, Carino-linked over the run (`attribution_detail.brinson`; research 115). The quick attribution on every report does not include Brinson; the detailed one does.

**Data and freshness:** Holdings by month; sector weights and returns of the benchmark.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Allocation: being over- or underweight the right sectors. Selection: picking better stocks within sectors.
- Interaction: both at once; positive when you overweight sectors where your picks did well.

**What it does not tell you:** Whether the decisions were skill or luck.

**Traps:**

- Two versions exist: Brinson-Hood-Beebower measures allocation against raw sector returns; Brinson-Fachler against the sector's return over the whole benchmark. Name which.
- Ours is Brinson-Fachler; a Brinson-Hood-Beebower tool will give a different allocation figure.

**Related:**

- [beta-and-alpha](../performance/beta-and-alpha.md)

**Sources:**

- Brinson, Hood & Beebower (1986), Financial Analysts Journal; Brinson & Fachler (1985), Journal of Portfolio Management (search summaries, 2026-10-31).
- Research 114, 115.

## Example answers

**Q:** Most of the excess return is selection?

**A:** The stocks chosen beat their own sectors; sector weights added little. That is what a stock-picking strategy should show.
