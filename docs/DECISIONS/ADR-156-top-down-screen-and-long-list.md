# ADR-156 · Top-down sector screen tested; Stocks on the Move becomes the long-term list

- **Context:** Operator, 2026-11-08: a brief with daily picks, likely big movers and long-term and swing screeners "expected more than 20% a year", chosen top down (top 5 sectors, then industries, then stocks). Research 182 pre-registered six top-down models and tested them against the current lists.
- **Options:** (A) best returns: Stocks on the Move as the long list, swing A kept, results-drift picks shown; (B) research 182's pre-set rule: top-5-sectors basket (long) and top-down breakout (swing); (C) keep the 3-of-5 consensus.
- **Choice:** A, by the operator. `config/screener.yaml` `main_long: nse_github_stocks_on_the_move`; the swing list and its rule are unchanged; the top-down models stay on the page as information.
- **Why:** the sector funnel lowered every model's return (quality momentum 20.4% → 14.6% a year); Stocks on the Move made 21.5% a year 2016-2026 with the smallest worst fall (-29%) and the best worse half among long lists (0.65 against the consensus's 0.48 and the rule's pick, 0.60).
- **Cost if wrong:** it was chosen after seeing the results among about 30 screener configurations, so its backtest flatters it; paper outcomes in `screener_history.jsonl` are the check. Its losing years were 2018 (-9%) and 2025 (-1%).
