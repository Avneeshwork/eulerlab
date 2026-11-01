# 139 — How does Kite show a delivery stock carried overnight, and one sold today?

**Date:** 2026-11-01 · **Confidence:** high that carried delivery stock is in `holdings`, not `positions.net`, and that a same-day sale is a negative CNC net row (Kite's docs); medium that `holdings.quantity` falls by the sale (forum answers from Kite's side, none in the docs)

## Question

`KiteBroker.positions` read only `positions()["net"]` (T-4364). What does each Kite field hold for a delivery stock carried overnight, and for one sold out of holdings today?

## Sources, graded by who wrote them

Forum roles were read from each author's profile page. "Member" means no staff, moderator or administrator role is shown.

| # | Source | Author and role | Date | What it says |
|---|---|---|---|---|
| A | [Kite Connect 3, Portfolio](https://kite.trade/docs/connect/v3/portfolio/) | Zerodha, official docs | fetched 2026-11-01 | `quantity` "Realised Quantity(T+2)"; `t1_quantity` "Quantity on T+1 day after order execution"; `used_quantity` "Quantity sold from the net holding quantity"; `opening_quantity` "Quantity carried forward over night"; `realised_quantity` "Quantity delivered to Demat". Positions: `net` is "the actual, current net position portfolio"; "Equity positions carried overnight move to the holdings portfolio the next day." **Silent on what a sale does to `quantity`.** |
| B | [Kite user manual, Portfolio](https://kite.trade/docs/kite/portfolio/) | Zerodha, official | fetched 2026-11-01 | Sold holdings show "as a negative quantity in the positions menu" until the end of that day, as CNC sell positions. Buying back the same day is an intraday trade |
| C | [Zerodha support: sold shares as a negative position](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-holdings/articles/why-does-shares-sold-from-holdings-show-up-as-a-new-negative-position-under-on-kite) | Zerodha support, official | fetched 2026-11-01 | The sold quantity "appears as negative in the positions window and decreases from the holdings page". About the app screen, not the API |
| D | [Forum 14948](https://kite.trade/forum/discussion/14948/com-zerodhatech-models-holding-quantity-vs-realisedquantity) | sujith, Administrator and Moderator | April 2025 | "`quantity` signifies how much you hold in the DEMAT account." "`realised_quantity` it is a legacy quantity field, don't use this." "`used_quantity` denotes the holdings units sold today. It will get reset to 0 the next day." |
| E | [Forum 2053](https://kite.trade/forum/discussion/2053/status-of-sold-shares-in-holdings) | sujith, Administrator and Moderator | August 2017 | A sale shows in positions as -20 and "It will reduce the quantity of your holdings to 0 immediately." The only administrator statement that `quantity` falls; nine years old |
| F | [Forum 16259](https://kite.trade/forum/discussion/16259/holdings-quantity-vs-used-quantity-after-an-intraday-partial-sale-of-a-settled-cnc-holding) | nagavenij, Member (writes for the Kite team: "We are looking into this") | September 2026 | "The `quantity` field is reduced corresponding to the executed CNC sell quantity." 100 settled, sell 40: `quantity` 60, `used_quantity` 40, net CNC -40 |
| G | [Forum 16275](https://kite.trade/forum/discussion/16275/holdings-and-positions-after-a-same-day-cnc-sale-when-t1-quantity-is-also-non-zero) | nagavenij, Member | September 2026 | 60 settled + 40 T1, sell 50: `quantity` 10, `t1_quantity` 40, `used_quantity` 50, net CNC -50. The sale comes out of settled shares first |
| H | [Forum 15315](https://kite.trade/forum/discussion/15315/why-quantity-t1-quantity-realised-quantity-for-this-holding) | a user's real response; Nivas, Moderator | 2025 | A real holding: `quantity` 15, `t1_quantity` 15, `opening_quantity` 30, `used_quantity` 0. Nivas: "Only the t2 quantity will show up in the `quantity` field." |
| I | [Forum 15333](https://kite.trade/forum/discussion/15333/understanding-the-response-of-holdings-api) | nagavenij, Member; mahak0802, user | July–August 2025 | Total holdings = `quantity` + `t1_quantity` + MTF quantity. The user found `quantity + t1_quantity + used_quantity` matched their account "in most of the cases" (not with MTF) |
| J | [zerodha/kiteconnect-mocks `holdings.json`](https://raw.githubusercontent.com/zerodha/kiteconnect-mocks/main/holdings.json) | Zerodha, official test data | fetched 2026-11-01 | Every row has `opening_quantity` = `quantity` + `t1_quantity` with `used_quantity` 0; one row has `quantity` 1, `opening_quantity` 1 and `mtf.quantity` 1000, so MTF shares are outside `opening_quantity` |
| K | [Forum 14577](https://kite.trade/forum/discussion/14577/not-getting-quantity-and-price-for-certain-stocks-via-getholdings) | DhanushK; posted data | November 2024 | Short-delivered shares show `quantity`, `t1_quantity` and `opening_quantity` 0 with `short_quantity` non-zero |
| L | [OpenAlgo's Zerodha adapter](https://raw.githubusercontent.com/marketcalls/openalgo/main/broker/zerodha/mapping/order_data.py) | open source | fetched 2026-11-01 | Uses holdings `quantity` alone and `net` alone; does not combine them. No help on this question |

## Findings

1. **Stated by Kite's docs (A, B):** delivery stock carried overnight is in `holdings`, not `positions.net`. A same-day sale out of holdings is a negative CNC row in `positions.net`. `opening_quantity` is the quantity carried forward overnight.
2. **Stated by an administrator (D):** `used_quantity` is the holding units sold today, reset to 0 the next day.
3. **Stated by Kite-side forum answers, not the docs (E, F, G), and agreed by the support page (C) and one user's account (I):** `holdings.quantity` falls by the sale on the same day. No source says it does not.
4. **Shown in real and official data (H, J):** `opening_quantity` = `quantity + t1_quantity` when nothing was sold; MTF shares are outside it.
5. From F and G together: after a sale, `quantity + t1_quantity + used_quantity = opening_quantity` (60 + 0 + 40 = 100; 10 + 40 + 50 = 100).

## Not found

- A statement in Kite's docs, or by an administrator in the last nine years, that `quantity` falls on a sale.
- Whether `opening_quantity` changes during the day for any reason (a same-day buy-back of sold holdings, a corporate action, a pledge).
- How `collateral_quantity` (pledged shares) relates to `quantity` and `opening_quantity`.
- Which bucket a sale uses when both settled and T1 shares are held: G says settled first, E (2017) says T1.

## Decision

`KiteBroker.positions` = each holding's `opening_quantity` + the net book, per symbol. This uses only the docs' definitions (findings 1 and 4) and gives the same answer whether or not `quantity` falls. As a check, each holding must satisfy finding 5; if it does not, if `opening_quantity` is missing, or if the row holds MTF shares, the call raises `BrokerUnreachable` rather than guess. The first version (holdings `quantity + t1_quantity` + net) would have counted every sale twice (HISTORY #55).

## Open questions

Record `holdings()` and `positions()` from the operator's own account before and after one real sale, after the close and next morning (T-4367). That settles finding 3 and the first two "not found" items for this account. A-091 stays open until then.
