"""What the assistant may look at. Every tool reads; none writes.

The model is never handed a file or a database. It is handed this list, asks
for the tools a question needs, and gets back a short piece of text. So what
can reach the hosted model is exactly what these functions return, capped at
`MAX_CHARS` each — and that list is shown to the operator under every answer.

### What is deliberately absent

- Anything that places, changes or stops an order (the same rule as the
  Telegram bot, ADR-063).
- Anything that runs a backtest. A run spends a trial, and `CLAUDE.md` says
  the trial counter is never bypassed.
- The holdout. `read_document` opens only documentation folders, never `data/`.
- Credentials. No tool reads `.env`; `redact.scrub` is the second lock.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_CHARS = 3500
"""Cap on one tool's answer. The free tier meters tokens per minute, and a
question rarely needs more than a page."""

DERIVED = Path("data/derived")
READABLE = ("docs", "hypotheses", "research")
READABLE_FILES = ("STATE.md", "TASKS.md", "README.md")
"""The only places `read_document` opens. Not `data/`, not `config/`, not `.env`."""

STUDIES = (
    "gap_forecast",
    "intraday_papers",
    "session_studies",
    "options_strategies",
    "india_papers",
)
RESULT_FILES = ("strategy_results", "adopted_results", "walk_results")
LONG_LIST = 12
PAGE = MAX_CHARS - 100
"""One page of a document. Under the cap, so the note saying where the next
page starts is not itself cut off."""
MAX_PRICE_DAYS = 120


@dataclass(frozen=True)
class Tool:
    description: str
    parameters: dict[str, Any]
    run: Callable[[Mapping[str, Any]], str]


def _clip(text: str, limit: int = MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[cut: {len(text) - limit} more characters not sent]"


def _slim(value: Any) -> Any:
    """Drop long series. A 2,000-point equity curve answers no question in words."""
    if isinstance(value, dict):
        return {k: _slim(v) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > LONG_LIST:
            return f"[{len(value)} items left out]"
        return [_slim(v) for v in value]
    if isinstance(value, float):
        return round(value, 4)
    return value


def _number(args: Mapping[str, Any]) -> str:
    return str(args.get("number") or "")


# --- deployments: the same read-only answers the Telegram bot gives ----------------


def _deployments(_: Mapping[str, Any]) -> str:
    from eulerlab import telegram_bot

    return telegram_bot.status()


def _positions(args: Mapping[str, Any]) -> str:
    from eulerlab import telegram_bot

    return telegram_bot.positions(_number(args))


def _orders(args: Mapping[str, Any]) -> str:
    from eulerlab import telegram_bot

    return telegram_bot.orders(_number(args))


def _next_rebalance(args: Mapping[str, Any]) -> str:
    from eulerlab import telegram_bot

    return telegram_bot.upcoming(_number(args))


def _data_coverage(_: Mapping[str, Any]) -> str:
    from eulerlab.ingest import coverage

    rows = coverage.table()
    return "\n".join(f"{r.name}: {r.status}, last {r.last or 'never'}" for r in rows)


# --- strategies and their results ------------------------------------------------------


def _strategies(args: Mapping[str, Any]) -> str:
    from eulerlab.strategies import REGISTRY

    needle = str(args.get("search") or "").lower()
    found = [
        d
        for d in REGISTRY.values()
        if not needle or needle in f"{d.id} {d.title} {d.summary} {d.kind}".lower()
    ]
    if not found:
        return f"No strategy matches '{needle}'. There are {len(REGISTRY)} in the library."
    if len(found) > 25:
        lines = [f"{d.id}: {d.title}" for d in found]
        return f"{len(found)} strategies. Search to see details.\n" + "\n".join(lines)
    return "\n\n".join(
        f"{d.id}: {d.title}\n{d.kind}, {d.asset_class.value}, {d.timeframe.value}\n"
        f"{d.summary}" + (f"\nSource: {d.source}" if d.source else "")
        for d in found
    )


def _library_result(strategy_id: str) -> str:
    """What the Strategies screen shows for one strategy: its latest run."""
    from eulerlab import results as result_store
    from eulerlab import workspace as workspace_mod

    summary = result_store.summary(workspace_mod.resolve(None), strategy_id)
    if not summary.get("runs"):
        return ""
    return json.dumps(_slim(summary), default=str)


def _results(args: Mapping[str, Any]) -> str:
    wanted = str(args.get("strategy_id") or "").strip()
    out: list[str] = []
    for name in RESULT_FILES:
        path = DERIVED / f"{name}.jsonl"
        if not path.exists():
            continue
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if wanted and row.get("strategy_id") != wanted:
                continue
            latest[(str(row.get("strategy_id")), str(row.get("symbol")))] = row
        for row in latest.values():
            if wanted:
                out.append(f"{name}: {json.dumps(_slim(row), default=str)}")
            else:
                out.append(
                    f"{name}: {row.get('strategy_id')} on {row.get('symbol')}: "
                    f"net {row.get('net_pnl', row.get('winner_oos_pnl'))}, "
                    f"Sharpe {row.get('sharpe', row.get('winner_oos_sharpe'))}"
                )
    if wanted:
        library = _library_result(wanted)
        if library:
            out.insert(0, f"library (latest daily run): {library}")
    if not out:
        return f"No stored result for '{wanted}'." if wanted else "No stored results."
    return "\n".join(out)


def _study(args: Mapping[str, Any]) -> str:
    name = str(args.get("name") or "")
    if name not in STUDIES:
        return f"Unknown study '{name}'. Choose one of: {', '.join(STUDIES)}."
    path = DERIVED / f"{name}.json"
    if not path.exists():
        return f"{name} has not been run on this machine."
    return json.dumps(_slim(json.loads(path.read_text(encoding="utf-8"))), default=str)


# --- documents -----------------------------------------------------------------------------


def _allowed(raw: str) -> Path | None:
    """`raw` as a path inside the readable folders, or None.

    Resolved before the check, so `docs/../.env` and a symlink out of the tree
    both fail it.
    """
    root = Path.cwd().resolve()
    target = (root / raw).resolve()
    if not target.is_file() or not target.is_relative_to(root):
        return None
    relative = target.relative_to(root)
    if relative.as_posix() in READABLE_FILES or relative.parts[0] in READABLE:
        return target if target.suffix in (".md", ".yaml", ".yml", ".txt") else None
    return None


def _find_documents(args: Mapping[str, Any]) -> str:
    words = [w for w in str(args.get("search") or "").lower().split() if w]
    hits: list[tuple[int, str, str]] = []
    paths = [Path(name) for name in READABLE_FILES]
    for folder in READABLE:
        paths += sorted(Path(folder).rglob("*.md")) + sorted(Path(folder).rglob("*.yaml"))
    for path in paths:
        if _allowed(path.as_posix()) is None:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        title = next((ln.strip("# ").strip() for ln in text.splitlines() if ln.strip()), "")
        lowered = f"{path.as_posix()} {text}".lower()
        score = sum(lowered.count(w) for w in words) if words else 1
        if score and all(w in lowered for w in words):
            hits.append((score, path.as_posix(), title[:90]))
    if not hits:
        return "No document matches."
    hits.sort(key=lambda h: (-h[0], h[1]))
    return "\n".join(f"{path} — {title}" for _, path, title in hits[:25])


def _read_document(args: Mapping[str, Any]) -> str:
    raw = str(args.get("path") or "")
    path = _allowed(raw)
    if path is None:
        return (
            f"'{raw}' cannot be read. Only documents under "
            f"{', '.join(READABLE)} and {', '.join(READABLE_FILES)} can."
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        start = max(int(args.get("offset") or 0), 0)
    except (TypeError, ValueError):
        start = 0
    piece = text[start : start + PAGE]
    rest = len(text) - start - len(piece)
    return piece + (
        f"\n[{rest} more characters; ask with offset {start + PAGE}]" if rest > 0 else ""
    )


# --- prices ---------------------------------------------------------------------------------


def _prices(args: Mapping[str, Any]) -> str:
    symbol = str(args.get("symbol") or "").upper().strip()
    if not symbol or '"' in symbol:
        return "Give an NSE symbol, for example RELIANCE."
    try:
        days = min(max(int(args.get("days") or 20), 1), MAX_PRICE_DAYS)
    except (TypeError, ValueError):
        days = 20
    path = DERIVED / "price_panel.jsonl"
    if not path.exists():
        return "The price panel has not been built."
    needle = f'"s": "{symbol}"'
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if needle in line:
                rows.append(json.loads(line))
    if not rows:
        return f"No daily prices for {symbol} in the NSE panel."
    last = rows[-days:]
    first, final = float(last[0]["c"]), float(last[-1]["c"])
    head = (
        f"{symbol}: {len(last)} sessions {last[0]['d']} to {last[-1]['d']}, "
        f"close {first} to {final} ({final / first - 1:+.1%}). Raw closes, not adjusted."
    )
    return (
        head
        + "\ndate,open,high,low,close,volume\n"
        + "\n".join(f"{r['d']},{r['o']},{r['h']},{r['l']},{r['c']},{int(r['v'])}" for r in last)
    )


# --- the list ---------------------------------------------------------------------------------

_NONE: dict[str, Any] = {"type": "object", "properties": {}}
_WHICH: dict[str, Any] = {
    "type": "object",
    "properties": {
        "number": {
            "type": "integer",
            "description": "Deployment number from `deployments`. Default 1.",
        }
    },
}


def _text(name: str, description: str, required: bool = False) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {name: {"type": "string", "description": description}},
    }
    if required:
        schema["required"] = [name]
    return schema


TOOLS: dict[str, Tool] = {
    "deployments": Tool(
        "Every paper or live deployment: mode, strategy, equity, return, last day traded.",
        _NONE,
        _deployments,
    ),
    "positions": Tool(
        "What one deployment holds now, with values and weights.", _WHICH, _positions
    ),
    "orders": Tool("The last ten orders (trades) of one deployment.", _WHICH, _orders),
    "next_rebalance": Tool(
        "What one deployment would hold after its next rebalance, and when.",
        _WHICH,
        _next_rebalance,
    ),
    "data_coverage": Tool(
        "Every dataset with its status (ok, behind, stale, missing) and last date.",
        _NONE,
        _data_coverage,
    ),
    "strategies": Tool(
        "Strategies in the library: id, title, kind, market, summary, source.",
        _text("search", "Words to match in the id, title or summary. Empty lists all ids."),
        _strategies,
    ),
    "strategy_results": Tool(
        "Stored backtest and walk-forward results. Without an id, one line per result.",
        _text("strategy_id", "A strategy id from `strategies`, for the full numbers."),
        _results,
    ),
    "study": Tool(
        "The stored output of one research study, with long series left out.",
        {
            "type": "object",
            "properties": {"name": {"type": "string", "enum": list(STUDIES)}},
            "required": ["name"],
        },
        _study,
    ),
    "find_documents": Tool(
        "Search research notes, decisions, runbooks, hypotheses, history, tasks and state. "
        "Returns paths and titles.",
        _text("search", "Words that must all appear in the document."),
        _find_documents,
    ),
    "read_document": Tool(
        "Read one document found with `find_documents`, a page at a time.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "A path from `find_documents`."},
                "offset": {"type": "integer", "description": "Character to start at. Default 0."},
            },
            "required": ["path"],
        },
        _read_document,
    ),
    "prices": Tool(
        "Recent daily prices of one NSE symbol from the price panel.",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "NSE symbol, for example RELIANCE."},
                "days": {
                    "type": "integer",
                    "description": f"Sessions, 1 to {MAX_PRICE_DAYS}. Default 20.",
                },
            },
            "required": ["symbol"],
        },
        _prices,
    ),
}
"""Every tool the model can call. All read-only; see the module docstring."""


def schemas() -> list[dict[str, Any]]:
    """The tools in the shape the chat API takes."""
    return [
        {
            "type": "function",
            "function": {"name": name, "description": t.description, "parameters": t.parameters},
        }
        for name, t in TOOLS.items()
    ]


def call(name: str, raw_arguments: str) -> str:
    """Run one tool. A bad name or bad arguments is an answer, not an exception."""
    tool = TOOLS.get(name)
    if tool is None:
        return f"There is no tool '{name}'. Tools: {', '.join(TOOLS)}."
    try:
        args = json.loads(raw_arguments) if raw_arguments.strip() else {}
    except json.JSONDecodeError:
        return "The arguments were not valid JSON."
    if not isinstance(args, dict):
        args = {}
    try:
        return _clip(tool.run(args))
    except Exception as exc:  # a broken tool tells the model, it does not end the chat
        return f"{name} failed: {type(exc).__name__}: {str(exc)[:200]}"
