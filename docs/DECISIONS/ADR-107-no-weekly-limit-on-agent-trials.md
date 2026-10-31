# ADR-107: No weekly limit on the agents' trials

- **Context:** ADR-089 let the idea lab spend 5 trials a week. On 2026-10-31 the operator said: "instead of 5 trials a week make it unlimited how much we needed", and asked for a Sharpe bar that does not depend on the raw trial count (research 138).
- **Options:** (a) Keep 5. (b) Raise to a bigger number. (c) No limit, every trial still logged before its result is read.
- **Choice:** (c). `config/agent_trials.yaml` `per_week: null`; `Allowance.per_week` is `int | None`, None meaning no limit. With no limit the lab tests up to 1,000 cards a run instead of 3. A number puts a cap back; 0 stops testing.
- **Why:** The operator's instruction. The ledger and the logging-before-reading rule are unchanged, so nothing is hidden. Research 138 proposes a bar that does not rise with repeats of one idea, which removes the reason for rationing.
- **Cost if wrong:** Until the gate's bar changes (T-4300), each agent trial still raises today's ledger-count bar, so an unlimited lab can push it up quickly. A bigger search also finds more lucky strategies; the gate, the holdout and forward paper are what stop them.
