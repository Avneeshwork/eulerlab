# An order is stuck in UNKNOWN

**Symptom.** `make reconcile-book` or a paper run reports one or more orders in
`UNKNOWN`, and the count does not fall on a retry. The kill switch may have
tripped with *"N orders in UNKNOWN — the broker link is unhealthy"*.

**What it means.** The system sent something and does not know whether the
broker has it. This is a modelled, expected state, not a crash. The order may
be resting at the exchange right now.

**Diagnosis, in order.**

1. `make reconcile-book` — it recovers, queries and prints. Look at whether the
   count of unresolved orders is falling between runs. If it is, the broker
   link is recovering and no action is needed.
2. If the count is static, the query itself is failing. Check the broker
   session first: `make kite-login` (the access token expires at 6 AM daily).
   An expired token makes every query fail while sends may still appear to
   work, which is exactly this symptom.
3. Look at the order in the journal:
   `grep <client_order_id> data/oms/paper/orders.jsonl` — the last event tells
   you which side of the send it died on. `send_ambiguous` after `created`
   means the network call itself failed; `process_restart` means a crash.
4. **Check the broker's own interface.** The whole point of `UNKNOWN` is that
   our records cannot answer this. The broker's order book can.

**Fix.**

- If the broker has the order and it filled: nothing to do, the next
  successful `resolve_unknown` will adopt it. Do not enter it by hand.
- If the broker has no record: the next successful query resolves it to
  `UNSENT`. Again, nothing by hand.
- If the broker's answer contradicts our recorded fills, `resolve_unknown`
  refuses to resolve it and reports a **break**. That one is a human decision
  and needs the broker's contract note to settle.

**What not to do.**

- Do not delete the journal line. Sequence numbers make the deletion visible
  and the journal will then refuse to load at all.
- Do not resubmit the order. The client order id is deterministic, so a
  resubmit is a no-op — but if you construct a *new* id to force it through,
  you have just double-sent.
- Do not add a timeout that gives up. There is deliberately no event for it
  (ADR-028).

**Prevention.** `max_unresolved_orders` in `config/killswitch.yaml` stops new
orders once a few pile up, so an unhealthy link produces three stuck orders
rather than thirty.
