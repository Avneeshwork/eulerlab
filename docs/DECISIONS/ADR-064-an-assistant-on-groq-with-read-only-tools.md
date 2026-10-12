# ADR-064 — The assistant: Groq with retention off, and read-only tools

**Context.** Operator, 2026-10-11: a free assistant for questions about data,
strategies, research and trades, with "no data leak to ai" and a floating
icon. This Mac cannot hold a local model (8 GB memory, 1.4 GB disk free), so
the operator asked for a cloud plan. Research 073.

**Options.** (a) A local model: no leak, does not fit. (b) The operator's own
free Oracle server: no AI company sees anything, but two CPU cores, slow.
(c) Groq's free API with Zero Data Retention on: fast, but each question
passes through Groq. (d) Gemini's free tier: trains on prompts, ruled out.

**Choice.** (c), chosen by the operator on 2026-10-12. `assistant/chat.py`
sends to the provider named `assistant` in `config/llm.yaml`. The model gets
no files, only the eleven read-only tools in `assistant/tools.py`. Three locks:
only approved hosts (`ALLOWED_HOSTS`); off until `EULERLAB_ASSISTANT_ZDR=1`
says retention was turned off; every request scrubbed of every `.env` value.
The panel shows the host, and under each answer what was sent.

**Why.** With tools, what can leave is a short, known list instead of "the
data". No tool trades, runs a backtest (that would spend a trial) or opens
`data/`, so the holdout and credentials are out of reach by construction.
The provider is one config line, so (a) or (b) is a later switch, not a rewrite.

**Cost if wrong.** If Groq's terms change or are not honoured, what leaked is
the questions asked and the tool answers to them: book values, strategy
results, research text. Not keys, not broker access. A-054 holds the recheck.
