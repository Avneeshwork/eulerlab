# ADR-091: Each agent run writes what it is doing, as it does it

- **Context:** The AI tab showed "running…" and then a summary. The operator asked to see what each agent is actually doing.
- **Options:** (a) stream the model's tokens; (b) each run appends short steps to `progress.jsonl` in its own folder, and the page polls; (c) a websocket from the runtime.
- **Choice:** (b). `Context.step(text)` appends `{at, kind, text}`. The runtime writes the start, every model request and answer, and the finish. `ctx.notes` is a `Trail` that reports each note as a step, so helpers that log through it (the paper agent) show without being changed. `GET /api/agents/activity` returns each agent's newest run (running, finished status, or `stopped`: no output and quiet for 15 minutes) and a feed of all steps. The Live view polls every 2.5 s while anything runs, 12 s otherwise.
- **Why:** Files are how agents already hand work on; a step file survives a crash and shows runs started by `make agent` or launchd, which the web server did not start. Model text is not logged (ADR-085), so (a) is out.
- **Cost if wrong:** Steps are what the worker chose to say, not a trace; a worker that never calls `step` shows only start, model calls and finish. Polling is a few small file reads per agent.
