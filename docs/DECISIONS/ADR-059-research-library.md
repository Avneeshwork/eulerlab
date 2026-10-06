# ADR-059: A research library of papers, each linked to the strategies that test it

**Context.** The operator asked for "a research paper repo" where every paper has a summary, trade idea and implementation logic and can be backtested directly. Paper knowledge was spread across `docs/RESEARCH/`, `hypotheses/` and strategy declarations, with no page to read or add one.
**Options.** A database table; Markdown files; one YAML file per paper with typed fields; papers as fields on strategy declarations.
**Choice.** `research/papers/<id>.yaml`, validated by `research/library.py` (pydantic), read and written by `/api/research/*`, shown on Tools → Research Library. A paper links to strategies (builder, registered or the Tweezer scanner); backtests go through the existing engines and dialog. "Build its rules" opens the Strategy Builder and links what is saved.
**Why.** Committed text diffs and reviews like code; a paper is the claim and a strategy one reading of it, so a failed backtest says "our reading failed"; no second run path.
**Cost if wrong.** The API writes into the repository tree, so papers added from the page must be committed by hand. A shared multi-user library would need a database.
