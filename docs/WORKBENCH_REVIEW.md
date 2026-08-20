# The workbench — UI, AI strategy authoring, and the architecture document
**Status:** COMPLETE
**Branch:** workbench-ui-ai   **Not a numbered sprint** — requested directly.

---

## What now works (plain English, no jargon)

**A web interface at `make workbench`.** Three ways to write a strategy, all
ending up as the same object the command line uses:

- **Describe** — type the idea in English, a model drafts it.
- **Compose** — pick a feature, how many names to hold, how often to rebalance.
- **Code** — write the function yourself.

Then press Run. You get an equity curve, the numbers, and — attached to every
result — a list of what the result does not mean.

**Pasted code is genuinely executed, and genuinely cannot cheat.** This was the
hard part. Executing arbitrary Python would have thrown away the protection the
whole project rests on: a strategy cannot see the future because the future is
not in the object it is handed, and arbitrary code could just open the data
file instead. So the sandbox removes every route out — no imports, no `open`,
no `eval`, no way to reach a class or a module. What is left can only do
arithmetic on what it was given. 35 tests, each a specific escape technique
someone would actually try.

**Any language model, and the default costs nothing.** The interface speaks the
one protocol every provider implements, so switching is a line of config. The
default runs on your own machine: no key, no quota, nothing sent anywhere.

**A document for someone who has never seen this.** `docs/ARCHITECTURE.md`,
949 lines, covering every component and the actual mathematics — how prices are
adjusted for splits and rights issues, why the median is used instead of the
mean, how the Deflated Sharpe Ratio works and why it rises with every strategy
tried, what purging and embargo do, how the Indian tax stack is computed. Every
formula is the one in the code, not one from a textbook.

---

## How to check it yourself (3 minutes)

```bash
make verify          # expect: 7 of 7 green, 983 tests
make workbench       # UI on :3000, API on :8000
```

In the browser:

1. **Compose** tab → pick `low_volatility` → Run. You get a curve and numbers.
2. **Code** tab → type `import os` at the top. It refuses **as you type**, with
   the reason.
3. Delete that and press Run. Custom code backtests through the real engine.

Read `docs/ARCHITECTURE.md` from the top. If any section does not make sense
without asking me, that section has failed and I want to know which.

---

## Two things I refused, and why

**Arbitrary `exec`.** You asked to give code and backtest it. The literal
implementation — take the string, run it — would have discarded the lookahead
firewall, because code that can `open()` a file does not need the `MarketView`
it was given. I built the capability anyway, by removing reach rather than
removing execution (ADR-032). You get to paste real Python; it just cannot
reach anything but its own arithmetic. If you want the unrestricted version,
say so and I will add it behind a flag that names what it costs — but the
number it produces would not be comparable with any other number here.

**Claiming specific free-model quotas.** You asked for "unlimited free models".
I have made the client work with any provider and defaulted it to one that is
genuinely free and unmetered because it runs locally. I have **not** written
"OpenRouter gives you N free requests" anywhere, because I have not verified it
and `CLAUDE.md` forbids inventing that kind of detail. The providers are listed
as endpoints; their limits are recorded as unverified (A-019).

---

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| The sandbox has no CPU limit (S-021) | It stops code reaching *data*, which is the security property. It cannot stop code being slow — CPython cannot safely interrupt a running expression. The wall-clock timeout reports an overrun rather than killing it | when this is exposed beyond your machine |
| No model is installed (S-022) | The default is local Ollama and it is not on this machine. The Describe tab says so; Compose and Code do not need it | one command: `ollama pull qwen2.5-coder:7b` |
| No authentication on the UI (T-3013) | It binds to localhost only. Fine on your laptop, not fine anywhere else | before it leaves this machine |
| Tier A is offered in the UI | It is a screen, not a backtest (ADR-021). The result labels it and the caveats repeat it, but it is still one click away | not a defect — it is labelled |

---

## What I could not verify

- **That the free hosted tiers work.** Not tested from here. The local default
  is the only one I can vouch for, and I could not test that either — Ollama is
  not installed. The code path is exercised by tests that feed it hand-written
  replies of the kind models produce.
- **Whether the architecture document actually lands for a newcomer.** I wrote
  it and I already know the system, which makes me the worst possible judge of
  whether it explains anything. That needs a reader who does not.
- **Anything about the strategies you will write in it.** The workbench makes
  backtesting fast and pleasant. That is a hazard, not a feature — see below.

---

## The thing I am most worried about

**This interface makes it enjoyable to try strategies, and trying strategies is
the expensive act.**

Every result in that UI is one backtest. The project's own arithmetic says a
candidate must beat **Sharpe 1.88** from noise alone, and the best thing this
project has ever produced is **1.27**. During testing I ran `low_volatility`
and got Sharpe **2.19** — above the bar, on a 599-day window, and almost
certainly meaningless. Then I ran a hand-written risk-adjusted momentum
strategy and got **0.10**.

If those two numbers make you want to run the first one through the gate, the
interface has done harm. The gate is deliberately not reachable from it, and
the backtests it runs are deliberately not counted as trials — but nothing stops
a person from browsing fifty strategies, finding the best-looking one, and then
registering *that* as though it were their first idea. The ledger cannot see
what happened in the browser.

That is the honest limitation of putting a fast interface on a slow discipline,
and I do not have a technical fix for it.

---

## Decisions I need from you

1. **Should the workbench log its runs to a separate, non-binding "exploration
   log"?** — Option A: yes, append every UI backtest to `data/derived/
   exploration.jsonl`, not counted as trials but visible, so a later
   registration can be checked against what was already browsed. Option B: no,
   keep the UI genuinely free. **My recommendation: A.** It costs nothing, it
   does not raise anyone's bar, and it is the only defence against the
   laundering path in the section above. Without it the trial ledger has a
   blind spot exactly where the temptation is highest.

2. **Do you want the unrestricted `exec` mode behind a flag?** — Option A: no,
   the sandbox is enough. Option B: yes, clearly marked, with results excluded
   from anything that touches the gate. **My recommendation: A** until you hit a
   strategy the sandbox genuinely cannot express, then revisit with that
   specific example — the restriction is easier to argue about against a real
   case than in the abstract.

3. **Should `docs/ARCHITECTURE.md` be the thing you hand to a prospective
   collaborator, or do you want a shorter non-technical version too?** It is
   currently written for someone technical who does not know finance.

---

## Reading added for you

- **Restricted execution and capability-based security** (SHOULD, 25 min) —
  why removing reach is a stronger guarantee than blocking known-bad patterns,
  which is the difference between this sandbox and a blocklist.
- **`docs/ARCHITECTURE.md` §5** (MUST, 30 min) — the validation mathematics.
  It is the section that explains why a Sharpe of 2.19 in that UI is not good
  news.

---

## Next

Nothing new is queued. Sprints 29–31 remain yours: static IP, broker
confirmation, CA review, then first capital. The two cheap things I can do on
your word are still T-1317 (recompute Sprint 8's IC on corrected prices) and
T-1407 (exercise the gate's PROMOTE path, which has never been taken).
