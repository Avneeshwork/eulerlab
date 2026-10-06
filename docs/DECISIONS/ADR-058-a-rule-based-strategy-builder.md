# ADR-058: A rule-based strategy builder, compiled to the one Strategy interface

**Context.** The builder offered "rank by one feature" or raw code. Nothing built there was saved, listed or reported, and the operator called it vague and asked for a new one built without reference to the old code.
**Options.** A node canvas (OpenAlgo Flow); nested blocks (Composer); rule rows with stops (Streak) inside a universe / signal / sizing / risk split (QuantConnect); a code editor.
**Choice.** Five steps — universe, entry rules, exit rules, sizing (with optional ranking), risk — stored as a validated JSON spec and compiled to `BuiltStrategy(Strategy)`. Stops are re-derived by replaying the rules over the view, cached per instrument. Builder strategies opt into `hold_unchanged` so the engines do not trade daily drift. Research 062.
**Why.** Rules read as sentences and can be summarised back exactly; a declared spec can do nothing the compiler does not, so no sandbox is needed; and it runs unchanged in Tier A, Tier B and paper.
**Cost if wrong.** A canvas or nested if/else is more expressive. The spec is versionless JSON, so adding block types later means a migration of saved specs.
