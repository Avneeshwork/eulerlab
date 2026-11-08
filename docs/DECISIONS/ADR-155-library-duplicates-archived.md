# ADR-155 · Duplicate strategies archived from the library

- **Context:** Operator, 2026-11-08: "remove if any strategy is multiple times in library". No id or title repeats, but several entries are the same rule under another id (a wider universe, another clock time, a parameter step, or HISTORY #85's same bet).
- **Options:** delete the cards; archive the extras (ADR-069); leave them.
- **Choice:** archive, keeping one entry per rule. Kept → archived: H-0096 → H-0098 (identical daily result); H-0161 → H-0160, H-0174, H-0178; H-0162 → H-0153; H-0121 → H-0118; H-0132 → H-0065; H-0022 → H-0020; H-0023 → H-0024, H-0025, H-0026; H-0027 → H-0028; H-0001 → momentum_12_1, india_wml_12_1; india_52w_high → fifty_two_week_high; india_illiquid_decile → illiquidity_premium; india_sharpe_momentum → india_sharpe_momentum_opt.
- **Why:** archiving only hides; results, reports, the trial ledger and any deployment are untouched, and Restore undoes it. Kept the version with the wider or point-in-time universe, the longer test, or the unoptimised parameters.
- **Cost if wrong:** a hidden variant that is a different bet; restore it from the library's Archived view. Left in: H-0146 (H-0132 plus a gap filter), H-0175 (correlation 0.39 with H-0161), india_frog_in_the_pan vs H-0021 and india_physical_momentum vs india_sharpe_momentum (different constructions).
