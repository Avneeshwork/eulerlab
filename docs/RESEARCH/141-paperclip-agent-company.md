# 141 — How do Paperclip and similar systems run AI agents as a company, and should eulerlab adopt one?

**Date:** 2026-11-02 · **Confidence:** high on Paperclip's concepts (its own docs and repo); medium on its data model and weaknesses (one secondary article and one vendor review)

## Question

The operator asked for "the Paperclip agent organisation model": agents as employees, managers who assign and ask for work, the operator as CEO approving the final work. What does Paperclip model, how do others do it, and should eulerlab run Paperclip or build the model itself?

## Sources

| # | Source | Kind | Fetched | What it says |
|---|---|---|---|---|
| A | [paperclipai/paperclip](https://github.com/paperclipai/paperclip) | the repo | 2026-11-02 | MIT. About 110k stars. Features: org chart, goals, heartbeats, budgets, governance, tickets, multi-organization. "Not an agent framework." No release listed |
| B | [Core concepts](https://docs.paperclip.ing/start/core-concepts) | official docs | 2026-11-02 | Company; agent = role + one manager + budget + adapter; the CEO agent is the only one without a manager and reports to the human board; tasks run backlog, todo, in_progress, in_review, done (blocked, cancelled); checkout gives exclusive ownership; heartbeats on schedule, assignment, comment, manual run, approval; approvals: strategy, hire, budget override; budgets warn at 80%, pause at 100%; adapters claude_local, codex_local, gemini_local, opencode_local, cursor, pi_local, hermes_local (http, process "coming soon") |
| C | [Mintlify page](https://mintlify.com/paperclipai/paperclip) | docs mirror | 2026-11-02 | Node.js 20+, pnpm 9.15+, embedded PostgreSQL, `npx paperclipai onboard --yes`, runs locally |
| D | [Paperclip deep dive](https://dev.to/truongpx396/paperclip-deep-dive-a-build-guide-for-an-ai-company-control-plane-dda) | secondary, DEV Community | 2026-11-02 | Tables `companies`, `agents` (`reports_to`), `issues` (`parent_id`), `heartbeat_runs`, `cost_events`, `approvals`, `activity_log`; checkout is one conditional UPDATE, 409 on conflict; approval types hire_agent, approve_ceo_strategy, budget_override_required, request_board_approval; "Local CLI adapters run unsandboxed on the host machine" |
| E | [Paperclip AI review 2026](https://fast.io/resources/paperclip-ai-review-2026/) | vendor blog (sells agent storage) | 2026-11-02 | Launched 2026-03-02. No built-in quality gate; testing found broken layouts and fabricated statistics; "Production-quality output still requires human review at every step." Cost figures unsourced |
| F | [CrewAI processes](https://docs.crewai.com/en/concepts/processes) | official docs | 2026-11-02 | Hierarchical process: a manager model allocates tasks by capability and reviews outputs. No human approval step described |
| G | [Hierarchical agent teams with LangGraph](https://kinde.com/learn/ai-for-software-engineering/ai-agents/hierarchical-agent-teams-with-langgraphsupervisor/) | secondary | 2026-11-02 | A supervisor routes subtasks to workers; teams of teams; no human interrupts described |

## Findings

- "Paperclick" is Paperclip (A, B). Its model is an org chart with one manager per agent, tickets with checkout, heartbeats, budgets and a human board that approves strategy, hires and budget overrides.
- eulerlab already had most parts: agent specs, daily request budgets, launchd schedules, an inbox, a hash-chained log. Missing: reporting lines, a ticket object, managers, goals.
- Paperclip's agents are coding CLIs with a shell (D). That would bypass `agents/boundaries.py`, which keeps agents away from the gate, the ledger, the order path and `subprocess`.
- Neither Paperclip (E) nor CrewAI or LangGraph (F, G) checks correctness; eulerlab's gate, skeptic and grounding check do.

## Decision

Build natively (ADR-123). The operator chose it on 2026-11-02.

## Not found

No Paperclip release notes or version number (A lists none). No primary source for Paperclip's database schema beyond D. No evidence on how Paperclip performs on quantitative research work.

## Open questions

Whether Paperclip's `http` adapter, once shipped, could drive eulerlab agents without a shell.
