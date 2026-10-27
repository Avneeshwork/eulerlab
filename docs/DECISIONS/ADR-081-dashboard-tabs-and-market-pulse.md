# ADR-081: Dashboard tabs and the market pulse

- **Context:** after ADR-080 the operator found the India dashboard hard to read, one long page of tables and a breadth chart, and asked for clearer UI, useful tabs, and the Breadth band replaced (research 121).
- **Options:** (a) keep one page and add explanations; (b) four tabs with a verdict first; (c) a single combined mood score, as Tickertape shows.
- **Choice:** (b): Overview, Sectors, Big money (F&O) and Stocks to watch. The Breadth band becomes four Market pulse cards (Trend, Participation, Fear, Big money), each a word from a printed rule, plus a template-written "What happened today". The thresholds are ours: Trend uses Nifty against its 200-day average and 3-month change; Participation 60/40% above the 50-day; Fear VIX percentile 30/70; Big money FII percentile 25/75.
- **Why:** retail platforms lead with a word and explain in place. Separate cards keep each rule checkable, where a combined score would hide which input moved it. Templates, not a model, so every sentence traces to one figure.
- **Cost if wrong:** the thresholds are judgement, not evidence. A word can mislead near a boundary (59.9% reads Mixed, 60% Broad). The figure and its rule sit on the card so the reader can check.
- **Superseded in part (2026-10-28) by ADR-082:** the template summary and the sentence on each card are removed; the tabs and the card rules stand.
