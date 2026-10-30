# ADR-094: Each agent shows on the page it works for

- **Context:** The operator, 2026-10-30: the agents "sitting in ai tab seems confusing as everything is at single place and not able to understand what to do". The data agent belongs with Data and Instruments, the research agent with the Research library, and so on.
- **Options:** (a) leave the agents in the AI tab and write a guide; (b) a strip at the top of each page with that page's agents, and the AI tab kept as the control room; (c) move each agent's whole view out of the AI tab.
- **Choice:** (b). `components/terminal/AgentStrip.tsx` holds `PAGE_AGENTS`, which maps each page to its agents. For each agent it gives the role and the next step in a trader's words. The strip shows an animated orb (it spins while the agent works), the last result or the live step, the inbox count, and Run now. The Dashboard shows the latest market brief itself. Engineering stays on the AI tab, because it reviews code, not trades. The guide is a Claude Doc, "How the AI agents help you trade".
- **Why:** It reads the same `/api/agents/activity` and `/api/agents/inbox` as the AI tab. So there is no new API and nothing to keep in sync. (c) would duplicate the inbox and settings.
- **Cost if wrong:** The strip takes a row at the top of six pages. If it feels heavy, it can collapse to the orb and one line.
