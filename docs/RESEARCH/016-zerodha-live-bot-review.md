# 016 — Review of the live Zerodha bot in `~/Documents/Trade`

**Reviewed:** 2026-08-21 · **Files:** `Backtest/LiveEngine.py` (401 lines),
`Broker/Zerodha.py` (490), `Broker/base.py` (65)

The operator asked for a look at the live trading bot deployed on the Zerodha
framework. This reviews it against the money-safety rules EulerLab holds its
own order path to — not because those rules are sacred, but because each one
exists for a failure that has actually happened to somebody.

**Summary: I would not run this against real capital in its current state.**
Five of the findings below can double-send an order or leave a position the
system does not know it holds. They are all fixable, and none requires
rearchitecting.

---

## Critical — can lose money without anyone noticing

### 1. There is no idempotency. A retry double-sends.

`place_order(self, unique_id, symbol, volume, ...)` at `Broker/Zerodha.py:159`
accepts a `unique_id`. **It is never used.** `grep unique_id Broker/Zerodha.py`
returns exactly one line: the signature.

The caller generates it as
`unique_id=f"{symbol}_{int(time.time())}"` (`LiveEngine.py:341`), which would
not help even if it were used: it is *timestamped*, so the same signal retried
one second later produces a different id. Deterministic means
`hash(strategy, signal_time, instrument, seq)` — the same intent must yield the
same id forever, which is the only thing that lets a broker reject the
duplicate.

**Consequence:** any retry — network blip, restart, operator re-run — places a
second real order.

### 2. A timeout is treated as a rejection

```python
except Exception as e:
    print(f"Error placing order: {e}")
    return None
```

`Broker/Zerodha.py:265-267` catches **every** exception and returns `None`. The
caller then does `if order_id:` (`LiveEngine.py:349`), so `None` reads as "not
placed".

But a network timeout is not "not placed" — it is *unknown*. The order may be
resting at the exchange right now. Collapsing three outcomes (landed, refused,
unknown) into two is the single most expensive modelling error in an order
path, and it costs money in both directions: assume it failed and you
double-send; assume it worked and you are short a position you think you hold.

**This is why EulerLab's state machine has an `UNKNOWN` state that only a
broker query can leave.** There is deliberately no timeout after which it
guesses.

### 3. A failed close still places the new order

```python
if current_position_size != 0:
    try:
        broker.close_position(symbol)
    except Exception as e:
        logger.error(f"Failed to close position: {e}")
# ... execution continues ...
order_id = broker.place_order(...)
```

`LiveEngine.py:313-341`. The reversal is two independent calls with no
transaction around them, and **the failure path only logs.** If the close
throws, the code proceeds to open the opposite position anyway — leaving a
doubled or hedged position that neither leg intended.

The narrower failure is just as bad: close succeeds, place fails, and the
system is flat while believing it is reversed.

### 4. Position state is in memory and dies with the process

`self.active_orders[order_id] = {...}` (`Zerodha.py:233`, `:253`) is a plain
dict on the adapter. A restart loses every record of what is open.

There is no journal — `grep -riE "journal|fsync"` across `Broker/` and
`LiveEngine.py` returns nothing. So after a crash there is no way to work out
what was in flight, and nothing to reconcile the broker's answer against.

The rule this violates is short: **the broker is the source of truth and local
state is a cache.** Here the cache is the only copy.

### 5. No kill switch, no rate limit

`grep -riE "kill.?switch|rate.?limit|max_orders"` across the broker and live
engine returns **nothing**.

There is no daily loss limit, no cap on orders per day, no consecutive-rejection
cut-out, and no orders-per-second governor. A signal function that starts
oscillating will trade until the money or the API quota runs out, whichever
comes first. SEBI's retail algo framework also treats order rate as a
regulatory boundary, so this is not only a risk question.

---

## Serious — wrong behaviour, visible if you look

### 6. The trade manager does not manage trades

```python
sl = last_price * 0.98 if action == "BUY" else last_price * 1.02
tp = last_price * 1.04 if action == "BUY" else last_price * 0.96
```

`LiveEngine.py:331-334`, under a comment that says `# TM calculates SL/TP`. It
does not. Unless `tm_name == "VwapTM"`, the stop and target are hardcoded 2% and
4% regardless of which TM was selected. The whole `TM_REGISTRY` is bypassed for
every other strategy.

### 7. A failed sizing calculation silently trades 10 units

```python
size = 10  # default fallback
if rm_name == "FullCapitalRM":
    try:
        ...
    except Exception as e:
        logger.error(f"Failed to get margin for FullCapitalRM: {e}")
```

`LiveEngine.py:320-329`. If the margin lookup throws, `size` stays at its
fallback and **a real order for 10 units is placed.** An inability to compute a
position size should stop the trade, not substitute an arbitrary number chosen
for testing.

### 8. `PRODUCT_CNC` is hardcoded

`Zerodha.py:171` and `:463`. CNC is delivery. An intraday strategy placed as
CNC takes delivery and carries the position overnight — different margin,
different risk, different tax treatment, and no auto-square-off. `exchange =
"NSE"` is hardcoded on the line above, so BSE-listed names cannot be traded at
all.

### 9. "Unsupported" and "failed" return the same value

```python
if trailing:
    print("Trailing stop-loss not supported with GTT orders")
    return None
```

`Zerodha.py:175-177`. A caller that asked for a trailing stop gets `None`,
identical to an order that failed — so a strategy relying on a trailing stop
silently never trades, and the log line is the only clue.

---

## What is worth keeping

The `BaseBroker` ABC (`Broker/base.py`) is a clean contract, and having
Zerodha and Alpaca behind one interface is the right shape — EulerLab's own
`BrokerAdapter` is the same idea. The GTT two-leg OCO construction in
`place_order` is genuinely useful and is the correct Kite primitive for a
bracket.

The problems are not in the structure. They are in what happens when something
goes wrong, which is the part that only matters after it does.

---

## The smallest change that makes it safe

In order of payoff per line changed:

1. **Deterministic client order ids, actually passed to Kite.** Kite accepts a
   `tag` on `place_order`; a hash of (strategy, signal time, symbol) in it makes
   duplicates detectable.
2. **Three return outcomes, not two.** Distinguish placed / refused / unknown,
   and on unknown, query rather than assume. Nothing else on this list matters
   as much.
3. **Write the intent to disk before the network call, and fsync it.** Reverse
   those two lines and a crash leaves an order at the exchange that no local
   record mentions.
4. **A daily loss limit and an order-count cap**, in a separate process from the
   strategy.
5. **Stop on a sizing failure** instead of falling back to 10.

Items 1–3 are perhaps a day's work and remove the double-send and lost-position
classes entirely.

---

## What I did not review

Order *cancellation* paths beyond a skim, the Alpaca adapter, the WebSocket
stream in `Stream/`, and whether the strategies themselves are sound. This was
a review of the live order path only.

**Confidence: high on findings 1–5**, which are structural and verified by
reading the code rather than inferred. Findings 6–9 are equally certain but
lower consequence.
