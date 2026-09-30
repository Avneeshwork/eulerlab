# ADR-049: An auditor for this codebase, not for code in general

## Status

Accepted, 2026-08-27.

## Context

Generic tooling already gates every commit here: ruff, ruff format, mypy
strict, and the full pytest suite. None of it caught the defects that actually
cost days this month.

| what shipped | what would have caught it |
| --- | --- |
| crypto, then US, then every winning exit billed Indian STT | nothing — `asset_class="equity"` is a valid default |
| a signal reading its whole history per bar | nothing — correct, just quadratic |
| an S3 listing that read 1,000 keys and stopped | nothing — the overflow reads as absent |
| a buy-and-hold benchmark billed intraday STT | nothing — `segment` defaulted |

They share a shape: **a plausible default silently applying the wrong thing, so
the numbers still look right.** A type checker cannot see it, because nothing
is mistyped. A test cannot see it unless someone already suspected it.

## Decision

Three passes, in decreasing certainty, in `src/eulerlab/audit`.

**`rules`** — deterministic AST checks, one per defect that has shipped. They
are narrow on purpose. A rule firing on "complexity" would be noise a reader
learns to skip; a rule firing on "a cost function that defaults its venue" is
a bug that has happened four times. Written against the AST rather than the
text because the interesting cases differ by where a bracket sits:
`_closes(window)[-n:]` and `_closes(window[-n:])` are the same characters in a
different order and one of them is quadratic.

**`smoke`** — invoke every registered strategy once and check the return shape.
The weakest useful claim, and the one nothing else made: eleven coded signals
were once unreachable from the console and nothing noticed until someone
clicked one.

**`review`** — a model reads the working diff. Advisory, structurally: its
findings are always NOTE and carry the model name. Two reasons. It is not
reproducible, so a gate on it would pass and fail the same commit; and it is
guessing about code it cannot run, while the rules encode defects that
actually shipped. Mixing an opinion with a checked fact makes the checked
facts look negotiable.

Also `--inventory`: every strategy with the file and function behind it. The
24 intraday signals live in two files and their ids do not match their
functions, so grepping an id finds the registry entry and not the code. Five
of them share a detect function with a US counterpart on purpose, and the
inventory names those as aliases rather than reporting them as duplicates.

## Consequences

The auditor found four latent defects on its first run, all `defaulted-venue`.
Three were dormant — every live caller passed `asset_class` explicitly — but
`benchmark.hold` passed no `segment` and took the router's default of
intraday, for a position held for years. On a Rs 1M NSE round trip that is
Rs 412 against Rs 2,250, because delivery STT is 0.1% on both sides against
0.025% on the sell alone. It understated what holding costs, which flatters
the benchmark and so understates every strategy measured against it.

The defaults are now gone from `fill_cost`, `candles_for`, `scan_symbol` and
`scan_many`, which is the same treatment `bracket.run` and `vector.run` got
when this bug class was first found.

`make audit` is not wired into pre-commit. The rules are fast and safe to gate
on, but the value here is a pass that gets run and read rather than one that
gets skipped with `--no-verify`; it stays a command until the rule set has
been wrong a few times and stopped being wrong.
