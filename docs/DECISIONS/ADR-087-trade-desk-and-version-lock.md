# ADR-087: A trade desk ticket per deployment, and a version lock on each strategy

- **Context:** The operator asked for a trade panel. A deployment trades whatever code its strategy has today, so an edit silently changes what a running book means.
- **Options:** (a) show orders after they happen; (b) a ticket before each rebalance with pre-trade checks, and a fingerprint of the strategy's source written at deployment; (c) freeze the code by copying it into the deployment folder.
- **Choice:** (b). `desk.py` builds one ticket per active deployment: sells, buys, estimated cost (A-068), reason, and checks for the kill switch, data grade, version lock, position size and order rate. `deploy/version_lock.py` writes `version_lock.json` on the first run. A paper book whose code changed keeps trading with a warning in its state. A live book stops before sending, and also stops unless that day's ticket is approved. `make relock DEPLOYMENT=... NOTE=...` accepts reviewed code.
- **Why:** A live order can then only follow a click on a ticket the operator read. (c) would duplicate code and hide engine fixes.
- **Cost if wrong:** The fingerprint covers the strategy's own source only, not the engine; an engine change is covered by `make verify`. The ticket has no VaR and no futures lot check yet (S-041, S-042). Live mode is still refused in `make_oms` (T-4022).
