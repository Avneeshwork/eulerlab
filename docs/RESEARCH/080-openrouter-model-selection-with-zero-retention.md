# 080 — Select OpenRouter models from its current zero-retention catalog

**Question.** The fixed free model IDs in `config/llm.yaml` returned OpenRouter's “No endpoints found matching your data policy” 404. How should the Research Library offer a usable model without weakening the retention rule?

**Sources, fetched 2026-10-15.**

| Source | URL | Finding |
|---|---|---|
| OpenRouter, model catalog API | https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties | `GET /api/v1/models` accepts `zdr=true` to return models with ZDR endpoints. It also supports maximum prompt/output price and supported-parameter filters. |
| OpenRouter, ZDR guide | https://openrouter.ai/blog/insights/zero-data-retention/ | Per-request `provider.zdr=true` routes only to endpoints with a ZDR policy; `data_collection: deny` is a separate control. The docs identify endpoint eligibility as dynamic and endpoint-specific. |
| OpenRouter, free models | https://openrouter.ai/collections/free-models | Free model inventory and rankings change over time. |

**Finding.** A static `:free` model name is not evidence that the model currently has a ZDR endpoint. The error is a safe refusal: OpenRouter did not route the prompt. The model catalog can be filtered for ZDR endpoints, free prompt and output pricing, and tool support, then cached briefly for the picker. Inference must continue to send both privacy constraints because catalog membership can change after discovery.

**Decision.** Research Library asks the configured OpenRouter provider for the live filtered catalog and offers those IDs. The server rejects overrides absent from that catalog and continues to enforce `zdr=true` and `data_collection=deny` on inference. If the filtered catalog is unavailable or empty, the operator can select a local model or Groq only when its ZDR lock is ready.

**Confidence.** High on the API filters and per-request controls from current OpenRouter documentation. The catalog does not guarantee that an endpoint will remain available at inference time; OpenRouter can still return the same fail-closed error.

**Open question.** The free ZDR catalog's exact size and coverage can change; no model is promised to remain available.
