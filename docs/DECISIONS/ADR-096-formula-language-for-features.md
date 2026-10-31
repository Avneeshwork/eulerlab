# ADR-096: Features can be written as formulas, interpreted, never executed

- **Context:** Research 130 found the research agent can only rank stocks by one of 10 hand-coded features, so it has almost nothing to search. The papers that work (AlphaAgent, R&D-Agent, Alpha Jungle) give the model an operator library. The operator approved Phase 1 on 2026-10-31.
- **Options:** (a) let a model write Python features and run them; (b) add hand-written features one at a time; (c) a small formula language of tested, past-only operators, parsed and interpreted.
- **Choice:** (c). `features/formula.py`: three inputs and 20 operators, at most depth 6 and 24 nodes, windows up to 504 sessions. A formula compiles to a `Feature`, and a card names it as `formula:<text>`; codegen, the critic and the idea lab resolve it through `formula.resolve`. The 10 library features are rewritten as the alpha zoo and match exactly on full histories.
- **Why:** (a) breaks the lookahead firewall and has no tests (`codegen.py`). (b) is too slow to search. (c) keeps both guarantees: a test checks that no value depends on a later row, for every operator.
- **Cost if wrong:** A wider search space makes it easier to overfit. Nothing here changes trial counting: every formula evaluated through the gate or the idea lab is a trial, as before. The search controls are Phases 2 to 5 of research 130.
