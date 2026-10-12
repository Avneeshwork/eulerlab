# ADR-068 — The Telegram bot answers far more, and still cannot act

**Context.** Operator, 2026-10-12: "build telegram bot more generalized and
more features make it broad". The bot answered eight words (ADR-063), took a
deployment by number only, cut a long answer short, and met a typing slip or a
plain question with the whole help list.

**Options.** (a) More read-only words and a looser way of reading a message.
(b) As (a), plus plain sentences passed to the assistant. (c) As (b), plus
words that act: run, stop, deploy, trip the kill switch.

**Choice.** (b). Twenty-two words in five groups: deployments (`status`,
`pnl`, `positions`, `orders`, `next`), market (`market`, `movers`, `price`,
`company`, `news`), research (`signal`, `strategies`, `results`, `trials`),
machine (`brief`, `data`, `jobs`, `kite`, `kill`) and the assistant (`ask`,
`forget`). A word can be shortened, a near miss is offered back, a deployment
is named by number or by part of its name, a long answer is split between
lines, and a keyboard of nine words sits under the text box. A message of
three words or more that starts with no word, or one ending in a question
mark, goes to the assistant; `EULERLAB_TELEGRAM_ASK=0` stops that.

**Why.** Everything added reads something the workbench already shows, so the
reasoning of ADR-063 stands: a chat is a weak place to hold the power to trade
or stop. `kill` reports the switch and cannot move it. `kite` reports the
login and never sends the login link, which carries the API key. The assistant
runs under ADR-064 unchanged (approved hosts, scrubbed requests, read-only
tools); a one- or two-word slip is not sent to it.

**Cost if wrong.** A sentence meant as a command goes to a cloud model: it is
the operator's own text, scrubbed of `.env` values, and each one spends some
of the free 50 requests a day. (c) is still a separate decision with its own
confirmation step (T-4049), not an extra entry in `COMMANDS`; a test pins the
list.
