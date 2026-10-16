# ADR-075 — Keep a daily Kite MCX instrument snapshot

**Context.** MCX contracts and their lot/tick terms need a current source. Kite exposes an exchange-specific instrument CSV (research 081).
**Options.** Manually copy contracts; mix MCX rows into the NSE instrument tree; preserve a dedicated daily snapshot.
**Choice.** Preserve the raw daily response under `data/landing/mcx/` and mirror it to the B2 `nse/mcx/` prefix.
**Why.** The source provides current contract terms, while an immutable daily copy makes future comparisons possible and keeps MCX isolated from NSE datasets.
**Cost if wrong.** This snapshot is not historical truth; it must not be used to reconstruct expired MCX contracts without historical exchange evidence.
