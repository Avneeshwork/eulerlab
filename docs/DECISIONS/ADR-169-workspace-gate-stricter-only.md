# ADR-169 — A workspace may tighten the platform gate, never loosen it

**Date:** 2026-11-12. **Status:** accepted (operator's decision card: "Platform gate, stricter only"). Issue #113, slice 3.

- **Context.** Each workspace needs its own gate settings (#113), but `mandate.yaml` and `gates.py` are operator-owned, and a platform that shows strategy results needs a bar nobody can lower.
- **Options.** (a) One gate for everyone; (b) each owner sets their own, looser included; (c) the platform's mandate is the floor and an owner may only raise it.
- **Choice.** (c). `accounts/gate.py`: `TIGHTENABLE` lists the numeric thresholds with one obvious stricter direction; `set_rules` stores a workspace's values in `workspace_gate` (migration 004, a history: newest version in force); `effective()` returns the mandate with them applied and the gate run passes it to `gates.decide(mandate=...)`. A looser value or any other key is refused, not clamped. `gates.py` and `mandate.yaml` are not edited. The ledger's gate entry records the workspace's rules beside the mandate version.
- **Why.** Results stay comparable across workspaces and no verdict on the platform was held to less than the operator's bar; cautious users can still raise it. The switches (`require_*`, `mode`, process rules, holdout date) stay the platform's: `simple` and `strict` test different things, so neither is "stricter".
- **Cost if wrong.** If owners need a switch, add it to `TIGHTENABLE` with its direction; nothing else changes. If the platform later raises a threshold above a workspace's stored value, the platform's applies (`effective` drops the stale value).
