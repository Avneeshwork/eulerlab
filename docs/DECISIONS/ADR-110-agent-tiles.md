# ADR-110: A page with several agents shows them as tiles

- **Context:** The operator, 2026-11-01: on Strategies the three agent cards sat side by side, each long and narrow, and the skeptic's findings ran far down the page. "Make each a icon and take full screen space to write instead of all 3 showing always."
- **Options:** (a) keep three cards and cap their height; (b) one small tile per agent (orb, name, status, time, inbox count), and the picked agent's full card opens below across the whole width; (c) tabs.
- **Choice:** (b), in `AgentStrip.tsx`. Nothing is open until a tile is picked; picking it again closes it, and changing page closes it. A page with one agent (Dashboard, Data, Instruments) still shows its card, so the market brief is not hidden behind a click.
- **Why:** The card text gets the full width, so long findings wrap in a few lines instead of dozens. The tiles still show at a glance which agent is working, done or waiting on you.
- **Cost if wrong:** A finding is one click further away. If that hides something urgent, open the tile of a running or failed agent by default.
