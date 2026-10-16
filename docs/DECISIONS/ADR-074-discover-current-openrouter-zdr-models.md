# ADR-074: Discover current free OpenRouter models with ZDR

**Context.** Static free model IDs lost ZDR endpoints, so the assistant and Research Library failed closed. Research 080 documents OpenRouter's live model filters.
**Options.** Weaken ZDR; hand-maintain model IDs; load current free ZDR models from OpenRouter and keep request-time enforcement.
**Choice.** Load a short-lived catalog filtered for free pricing, ZDR endpoints and tool support. Allow those model IDs through the existing approved OpenRouter provider only.
**Why.** Model and endpoint availability changes; the provider's catalog is the current eligibility source, while inference constraints remain the final guard.
**Cost if wrong.** Catalog membership can go stale between refresh and inference, so requests can still fail with no prompt sent; it does not certify model quality.
