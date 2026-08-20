# ADR-033 — Any OpenAI-compatible endpoint, defaulting to local

**Context.** The operator asked for the interface to be able to use "unlimited
free models". Free tiers exist, change without notice, and each vendor has its
own client library.

**Options.** (a) Integrate one vendor's SDK. (b) Integrate several SDKs behind
an abstraction. (c) Speak the one wire protocol they all implement —
`POST {base_url}/chat/completions` — and treat the provider as configuration.

**Choice.** (c), with `config/llm.yaml` listing endpoints and naming the
*environment variable* for each key, never the key. The default is local Ollama:
free, no key, no quota, nothing leaves the machine. Written with `urllib`, so
it adds no dependency.

**Why.** A free tier disappearing then costs one line of YAML rather than a
rewrite, and no vendor SDK enters the dependency tree. Local-by-default matters
more than model quality here because of what the model actually does: it drafts
a specification that is then validated by code and reviewed by the operator. A
weaker model gives a worse first draft; it cannot give a wrong backtest result.

**Cost if wrong.** A server claiming OpenAI compatibility may differ at the
edges; `_extract` reports the actual reply rather than raising a `KeyError`
from inside a helper. The specific free-tier limits are **not** verified and are
recorded as A-019 — `CLAUDE.md` forbids inventing API details, and the request
shape is the documented common interface, while the quotas are the vendors'
claims.
