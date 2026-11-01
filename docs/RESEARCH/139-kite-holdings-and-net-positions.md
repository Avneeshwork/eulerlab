# 139 — Where does Kite show a delivery stock carried overnight?

**Date:** 2026-11-01 · **Confidence:** high that carried delivery stock leaves `positions.net` for `holdings`; low on how a same-day sale out of holdings changes `holdings.quantity`

## Question

`KiteBroker.positions` read only `positions()["net"]` (T-4364). Does a CNC buy stay there after its day, and if not, which fields hold it?

## Sources

| Source | URL | Fetched | Read |
|---|---|---|---|
| Kite Connect 3, Portfolio | https://kite.trade/docs/connect/v3/portfolio/ | 2026-11-01 | Holdings and positions sections, field tables |
| Forum: "Understanding the response of holdings api" | https://kite.trade/forum/discussion/15333/understanding-the-response-of-holdings-api | 2026-11-01 | Whole thread |
| Forum: "GET Positions and Holdings API questions" | https://kite.trade/forum/discussion/8651/get-positions-and-holdings-api-questions | 2026-11-01 | Whole thread |
| pykiteconnect v4 docs | https://kite.trade/docs/pykiteconnect/v4/ | 2026-11-01 | `holdings()` and `positions()` docstrings |

## Findings

1. The docs: "Equity positions carried overnight move to the holdings portfolio the next day." `net` is "the actual, current net position portfolio"; `day` is the day's activity.
2. Holdings fields: `quantity`, `t1_quantity` ("Quantity on T+1 day after order execution. Stocks are usually delivered into DEMAT accounts on T+2"), `realised_quantity`, `used_quantity` ("Quantity sold from the net holding quantity"), `collateral_quantity`, `opening_quantity`.
3. Zerodha staff (thread 15333): the total holding needs `quantity` plus `t1_quantity` plus the MTF quantity.
4. A forum user (not staff, thread 8651): a sale out of holdings shows in positions as a CNC position, filterable by exchange and product.
5. `pykiteconnect.KiteConnect` has `holdings()`: "Retrieve the list of equity holdings."

## Not found

Whether `holdings.quantity` falls on the day a holding is sold, or only `used_quantity` rises. If it falls, adding the negative net position double-counts the sale. Recorded as A-091.

## Decision

`positions()` returns holdings (`quantity + t1_quantity`) plus the net book, per symbol; both calls must succeed. MTF is ignored: this platform does not use it.

## Open questions

Check A-091 on the first live day with a holding sold (S-015).
