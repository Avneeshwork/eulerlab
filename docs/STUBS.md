# STUBS — everything currently fake

Logged the moment it is created, not at review time. If it is stubbed, mocked,
hardcoded or otherwise not what it appears to be, it is in this table.

Empty rows are good news. A long table is not a problem in itself — an
*unlisted* stub is.

---

| ID | What | Where | Why it is fake | Real in |
|---|---|---|---|---|
| S-001 | `Order` model — four fields and `algo_id`, nothing else | `src/eulerlab/schemas.py` | Reserves the `algo_id` field before the OMS exists. Adding the field now is 5 minutes; adding it after the OMS, reconciler, event log and attribution all read the schema is a week of migrations. **This is not the order schema — do not build on it.** | Sprint 19 |
| S-002 | `max_orders_per_second: 5` — a number nothing reads | `config/execution.yaml` | The OPS governor is a config key with no enforcement, because there is no EMS. Present so the compliance sprint is a config change rather than a redesign. | Sprint 19 (enforcement), Sprint 29 (tuned + confirmed) |
| S-003 | `static_ip: null` | `config/deploy.yaml` | Placeholder. The real value is a fixed IP registered with the broker, which cannot be chosen until a VPS and a broker account exist. | Sprint 29 |
| S-004 | `region: ap-south-1` in the deploy config | `config/deploy.yaml` | Written down as the intended region. No cloud account exists, nothing is provisioned there, nothing validates the string. | Sprint 2 (VPS) |

---

## Not stubs, but worth stating plainly

These are not fake — they simply do not exist yet, and no code pretends
otherwise: market data, any downloader, any database, the security master, both
backtesters, any strategy, any broker connection. See `STATE.md`.
