# ADR-214 — The knowledge search treats words for one idea as one word

**Context.** Issue #159. Research 192 asked the knowledge tool "short-term reversal after quarterly results announcement" and found nothing, while "fade results gap reversal" found H-0040 and H-0168. The search is BM25 on raw words, so a fade, a reversal and a bounce were different ideas to it, and so were results and earnings.
**Options.** (a) Embeddings (a new dependency and a model to host); (b) a small synonym table applied to query and text alike; (c) leave it and tell agents to try several wordings.
**Choice.** (b). `knowledge_index.SAME` maps reversal (reverse, reversion, fade, contrarian, bounce, rebound), results (earnings, quarterly, EPS, PEAD), momentum (continuation, drift, persistence, trend), gap (overnight), volume (turnover), promoter (insider, SAST) and bulk (block) each to one term, in every search that uses the index.
**Why.** No dependency, checkable by reading one table, and it fixes the case that was found.
**Cost if wrong.** A word in two senses joins ideas it should not ("trend" as a filter, "overnight" as a holding period), lifting a near card above a nearer one. The table is hand-made and will miss wordings nobody has used yet.
