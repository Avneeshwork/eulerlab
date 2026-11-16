# ADR-212 — The generator eval reads a fixed lesson store

**Context.** Issue #157, T-4599. The generator eval asks the card writer whether it keeps each case's rule. The writer checks the agents' live lesson store, so on the Mac (which holds the two built-in lesson checks) three public cases and one held-out case failed, while CI, with no store, passed. The score measured the machine, not the role.
**Options.** (a) Change the cases' expectations to the Mac's lessons (the held-out file is operator-owned, so not without the operator); (b) run the solver against a fixed lesson store; (c) skip the lesson check in evals.
**Choice.** (b). `writer.accept` takes `lessons_root`; the eval passes a new, empty temporary folder each case. The lessons' own checks keep their own tests.
**Why.** An eval must give the same answer wherever it runs, and the cases were written for an empty store.
**Cost if wrong.** The eval no longer sees a lesson wrongly dropping a good rule; that is the lesson tests' job now.
