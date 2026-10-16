# ADR-073: Draft paper fields and sandboxed strategies with the assistant provider

**Context.** The operator wants the Research Library to fill paper fields and code/backtest from a paper page, using the existing AI setup.
**Options.** New agent stack; direct provider calls; reuse the assistant's locked provider and the existing authoring/backtest paths.
**Choice.** Draft from pasted source text through the assistant's host, retention and redaction checks; generate code through the existing sandbox and Tier B job. Show results without saving generated source.
**Why.** One provider policy and the established strategy firewall and engine keep this workflow reviewable.
**Cost if wrong.** A generated draft can omit paper details, and one backtest is weak evidence; source text is not fetched or retained.
