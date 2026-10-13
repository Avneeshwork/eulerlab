# ADR-069 — Archiving a strategy hides it, and does nothing else

**Context.** Operator, 2026-10-13: "add option in strategy library to archieve
some strategies and undo if wanted". The Strategies page lists 80 strategies,
most of them rejected, and the dead ones crowd the ones still being looked at.

**Options.** (a) Delete a strategy from the registry. (b) A hidden list kept in
the browser. (c) A hidden list kept on the server, per workspace.

**Choice.** (c). `strategies/archive.py` keeps `{id: date archived}` in
`workspaces/<id>/archived_strategies.json`. `/api/fleet` marks each strategy
`archived`; `POST /api/strategies/archive` puts ids away or brings them back.
On the Strategies page an archived strategy leaves the main list, an
"Archived N" filter shows them, and Archive / Restore sits in the side panel
and in the selection bar, for one strategy or many. Each change shows a line
with **Undo**.

**Why.** Deleting (a) would remove evidence: the noise bar counts every
configuration ever evaluated, and a rejected strategy that vanishes makes the
survivors look better than they are. So archiving touches no result, report,
trial or deployment, and restoring leaves no trace. The browser (b) would
forget the list on another machine and could not be read by anything else.

**Cost if wrong.** A strategy with a running paper deployment can be archived
and keeps trading while out of sight on this page; it is still on Live & Risk,
and the confirmation line says deployments are unchanged. The header still
counts all 80, archived included, on purpose. Removing the feature is deleting
one file per workspace.
