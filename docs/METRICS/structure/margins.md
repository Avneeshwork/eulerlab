# Margins: SPAN, exposure, peak margin

*Family: Market structure and trading rules. Id: `margins`.*

**In one line:** The money brokers must collect before you can hold a position.

**Where you see it:** Paper trading for futures; the risk view.

**How we compute it:** F&O: SPAN (covers a one-day 99% loss) plus exposure margin. Cash: VaR plus extreme loss margin. Since September 2021 the full margin is collected upfront and checked by at least four random intraday snapshots (peak margin).

**Data and freshness:** Clearing corporation files; broker.

**Do we hold it:** No.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Margin sets the leverage available; it rises when volatility rises, which can force position cuts.

**What it does not tell you:** Risk of the strategy itself.

**Traps:**

- Rules change; check NSE or SEBI before quoting (A-085).
- Sources differ on leverage caps; use SEBI's circular.

**Related:**

- [sebi-fno-rules](../policy/sebi-fno-rules.md)
- [value-at-risk](../risk/value-at-risk.md)

**Sources:**

- Broker summaries of SEBI's 2020 circular on peak margin (search summary, 2026-10-31).

## Example answers

**Q:** Why did my margin requirement jump?

**A:** Exchanges raise SPAN when volatility rises; on expiry day short options also carry an extra 2% extreme loss margin under the 2024 rules.
