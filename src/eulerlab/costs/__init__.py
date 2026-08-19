"""Indian transaction costs, versioned by effective date.

The rates changed inside the backtest window - futures STT went 0.0125% ->
0.02% -> 0.05% between 2024 and 2026 - so costs are a time-versioned schedule
queried with the trade date, not a constants file. See
`docs/RESEARCH/013-indian-transaction-costs.md`.
"""
