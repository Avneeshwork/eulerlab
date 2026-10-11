# ADR-063 — Telegram: deployments report their actions; the bot only answers

**Context.** Operator, 2026-10-11: "setup telegram signals for paper / live
trading strategies like name of strategy and strategy actions", then "define
terms i can use to interact with telegram". `notify.py` already sent job
failures to the operator's chat.

**Options.** (a) Messages out only. (b) Messages out, and a bot that answers
questions. (c) As (b), plus words that act: run, stop, deploy.

**Choice.** (b). `deploy/signals.py` sends a message when a deployment places
orders (strategy name, each order, equity) or halts; a run that only marks the
book sends nothing. `research/gap_signal.py` sends the gap strategy's decision
before the close. `telegram_bot.py` answers eight words (status, positions,
orders, next, signal, data, strategies, help) from the operator's chat only.
Every word is read-only, and a test pins the list.

**Why.** A chat is a weak place to hold the power to trade or stop: an unlocked
phone or a leaked token is enough. `CLAUDE.md` puts kill switches in a separate
process with separate credentials; this bot is neither. Answers carry no such
risk and are what the operator needs away from the machine.

**Cost if wrong.** Stopping a deployment still needs the workbench or a
terminal. If that proves too slow in practice, (c) is a new decision, with its
own confirmation step, not an extra entry in `COMMANDS`.
