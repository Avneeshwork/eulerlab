# ADR-032 — A sandbox, not `exec`: how pasted code stays inside the firewall

**Context.** The operator asked for an interface where a strategy can be given
as code or as text and backtested. ADR-027 refused to execute generated Python,
because a `Strategy` is safe from lookahead only while it can see nothing but
its `MarketView`, and arbitrary code can open the panel file directly.

**Options.** (a) Honour ADR-027 literally and offer only composition from
vetted primitives — refuses half the request. (b) `exec` the code — delivers
the request and discards the firewall. (c) Execute it with every route out
removed.

**Choice.** (c). Three layers: an allowlisted AST (no `import`, `while`,
`class`, `try`, `with`, `global`, decorators, generators), allowlisted
*attribute names* rather than merely "no dunders", and replaced builtins with
no `open`, `getattr`, `eval`, `type` or `__import__`. Names are resolved at
submit time so `open(...)` fails immediately with an explanation.

**Why.** The danger was never executing code — it was executing code with
**reach**. Remove every name that returns a file, a module, a class or a
namespace, and what remains can only do arithmetic on the view it was handed,
which is exactly the property the firewall needs. ADR-027 still governs the
*research loop*, where composition keeps every primitive tested; this covers
the workbench, where the operator is deliberately authoring something new.

**Cost if wrong.** An escape nobody anticipated would let a strategy read
future prices, and its backtest would look excellent. Mitigated by 35
adversarial tests, each a named technique, and by the allowlists being
deny-by-default so an unanticipated construct is refused rather than permitted.
This is **not** a defence against a hostile adversary with a CPU-exhaustion
attack (S-021); the threat model is the operator's own code, or a model's.
