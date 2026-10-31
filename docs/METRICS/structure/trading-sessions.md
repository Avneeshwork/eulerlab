# Trading sessions: pre-open, normal, closing

*Family: Market structure and trading rules. Id: `trading-sessions`.*

**In one line:** How the trading day is organised on NSE.

**Where you see it:** Intraday data; the opening price.

**How we compute it:** Pre-open call auction 09:00-09:15 sets one equilibrium opening price that clears the most volume; continuous trading from 09:15 to 15:30. From 8 December 2025 near-month futures also have a pre-open; options do not. Changes tied to a closing auction took effect 7 September 2026 (sources disagree on exact minutes).

**Data and freshness:** NSE.

**Do we hold it:** Minute bars (Kite) and index minutes.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- The opening print comes from the auction, not the first trade; gap strategies must use it (research 075).

**What it does not tell you:** Liquidity in the first minutes.

**Traps:**

- Rules change; check NSE or SEBI before quoting (A-085).
- Pre-open timings changed in 2026; check NSE's circular for the exact windows.

**Related:**

- [gift-nifty](../macro_global/gift-nifty.md)
- [circuit-breakers](../structure/circuit-breakers.md)

**Sources:**

- NSE pre-open pages; Business Today on F&O pre-open (search summary, 2026-10-31); research 075.

## Example answers

**Q:** Why does the open differ from the first trade?

**A:** The open is the price NSE's 09:00-09:15 call auction found to clear the most volume; continuous trading starts after.
