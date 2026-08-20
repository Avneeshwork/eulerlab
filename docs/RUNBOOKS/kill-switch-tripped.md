# The kill switch is tripped

**Symptom.** Every send raises `KillSwitchTripped`. `make kill-status` prints
`TRIPPED` and a reason.

**Diagnosis.** The reason recorded is the **first** one — later trips are
logged but do not overwrite it, because the first is the informative one and
everything after it is a consequence of having stopped.

```bash
make kill-status
```

`by: limits` means an automatic limit fired; the reason names which.
`by: operator` means a human did it. The full history, including every
redundant trip, is in `data/oms/killswitch_log.jsonl`.

**Before clearing it, in every case:**

1. `make reconcile-book` — confirm the position book agrees with the broker
   and no order is unresolved. Clearing the switch while the book is in doubt
   re-arms a system that does not know what it holds.
2. Understand the trip. A daily-loss trip on a genuinely bad day is the switch
   working. A trip from consecutive rejections is usually a misconfiguration —
   an untradable instrument, a stale session — and clearing it without fixing
   the cause just produces the same trip.

**Clearing it.** Needs `KILLSWITCH_TOKEN`, which the trading process never
loads and no other module may even name.

```bash
KILLSWITCH_TOKEN=... uv run python -m eulerlab.oms.killswitch --reset --note "why"
```

The note goes in the log. There is deliberately no `reset()` function anywhere
in the importable surface — the moment one exists, something calls it in a
retry loop at three in the morning.

**Honest limitation (S-019).** On one machine with one user account, a process
can delete `data/oms/KILL_SWITCH` directly. The separation here is by code
structure and credential, not by the operating system. Real separation means
a different user on a different host, and a second broker API key whose only
power is to square off and disable — so the switch still works when *this
machine* is the thing that is broken.
