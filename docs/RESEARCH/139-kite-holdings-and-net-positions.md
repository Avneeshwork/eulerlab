# 139 — Where does Kite show a delivery stock carried overnight?

**Date:** 2026-11-01 · **Confidence:** high that carried delivery stock leaves `positions.net` for `holdings`; medium that `holdings.quantity` falls on the day of a sale (forum answers, no staff badge, no docs statement)

## Question

`KiteBroker.positions` read only `positions()["net"]` (T-4364). Does a CNC buy stay there after its day, and if not, which fields hold it?

## Sources

| Source | URL | Fetched | Read |
|---|---|---|---|
| Kite Connect 3, Portfolio | https://kite.trade/docs/connect/v3/portfolio/ | 2026-11-01 | Holdings and positions sections, field tables |
| Forum: "Understanding the response of holdings api" | https://kite.trade/forum/discussion/15333/understanding-the-response-of-holdings-api | 2026-11-01 | Whole thread |
| Forum: "GET Positions and Holdings API questions" | https://kite.trade/forum/discussion/8651/get-positions-and-holdings-api-questions | 2026-11-01 | Whole thread |
| Forum: "Holdings quantity vs used_quantity after an intraday partial sale" | https://kite.trade/forum/discussion/16259/holdings-quantity-vs-used-quantity-after-an-intraday-partial-sale-of-a-settled-cnc-holding | 2026-11-01 | Whole thread |
| Forum: "Status of sold shares in holdings" (2017) | https://kite.trade/forum/discussion/2053/status-of-sold-shares-in-holdings | 2026-11-01 | Whole thread |
| Forum: "Why quantity ≠ t1_quantity + realised_quantity" | https://kite.trade/forum/discussion/15315/why-quantity-t1-quantity-realised-quantity-for-this-holding | 2026-11-01 | Whole thread |
| Zerodha support: sold shares show as a negative position | https://support.zerodha.com/category/trading-and-markets/general-kite/kite-holdings/articles/why-does-shares-sold-from-holdings-show-up-as-a-new-negative-position-under-on-kite | 2026-11-01 | Whole article |
| Kite user manual, Portfolio | https://kite.trade/docs/kite/portfolio/ | 2026-11-01 | Holdings section |
| pykiteconnect v4 docs | https://kite.trade/docs/pykiteconnect/v4/ | 2026-11-01 | `holdings()` and `positions()` docstrings |

## Findings

1. The docs: "Equity positions carried overnight move to the holdings portfolio the next day." `net` is "the actual, current net position portfolio"; `day` is the day's activity.
2. Holdings fields: `quantity`, `t1_quantity` ("Quantity on T+1 day after order execution. Stocks are usually delivered into DEMAT accounts on T+2"), `realised_quantity`, `used_quantity` ("Quantity sold from the net holding quantity"), `collateral_quantity`, `opening_quantity`.
3. Zerodha staff (thread 15333): the total holding needs `quantity` plus `t1_quantity` plus the MTF quantity.
4. A forum user (not staff, thread 8651): a sale out of holdings shows in positions as a CNC position, filterable by exchange and product.
5. `pykiteconnect.KiteConnect` has `holdings()`: "Retrieve the list of equity holdings."
6. Forum 16259 (nagavenij, who answers for Kite elsewhere; no staff badge): "The `quantity` field is reduced corresponding to the executed CNC sell quantity." 100 settled, sell 40: `quantity` 60, `used_quantity` 40, net CNC -40; `used_quantity` resets the next day.
7. Forum 2053 (sujith, 2017): a sale "will reduce the quantity of your holdings to 0 immediately"; a sale of undelivered shares is deducted from `t1_quantity` at once.
8. Forum 15315: a real holding with `quantity` 15, `t1_quantity` 15, `opening_quantity` 30, `used_quantity` 0, so `opening_quantity` includes T1.
9. Zerodha support: the sold quantity "decreases from the holdings page" (the app screen).

## Not found

A statement in Kite's own docs, or an answer with a staff badge, on what a sale does to `quantity`; what `opening_quantity` does after a same-day buy-back; how collateral and MTF quantities count. A-091.

## Decision

`positions()` returns each holding's `opening_quantity` plus the net book, per symbol, which is the same whether or not `quantity` falls on a sale. Each holding must satisfy `quantity + t1_quantity` (+ `used_quantity`) = `opening_quantity`; if not, it raises. The first version (holdings `quantity + t1_quantity` plus net) would have counted a sale twice (HISTORY #55).

## Open questions

Record `holdings()` and `positions()` before and after one real sale to close A-091 (S-015).
