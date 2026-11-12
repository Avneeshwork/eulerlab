"""Quantpedia's strategy database as a research source (docs/RESEARCH/125-quantpedia-api.md).

Quantpedia's API (Pro accounts, key on request) lists the strategies it has
catalogued from academic papers, each with the paper's own backtest numbers,
Quantpedia's recalculated ones, its source paper and notes on costs and
robustness. Here it is a source of *ideas and prior evidence*, never of
signals: a Quantpedia strategy reaches the platform only as a lead in the
research agent's inbox, and from there by the same card, trial and gate as any
paper.

    make quantpedia-sync          # land the list and up to 50 new strategy details

**Raw data rule.** Every response is landed as fetched under
`data/landing/quantpedia/<fetch day>/` with a line in `manifest.jsonl`
(url, SHA-256, knowledge time). Nothing landed is rewritten. A strategy's
detail is fetched once; a later run fetches only ids not yet landed, so a
sync is resumable and never re-downloads.

**Credentials.** `QUANTPEDIA_USERNAME` and `QUANTPEDIA_API_KEY` in `.env`
(HTTP Basic, as the API docs say). Without them every call here returns
nothing and says why; nothing else depends on this source.

The endpoints used are the three the API docs list: `GET /strategy`,
`GET /strategy/{id}`, `GET /strategy/{id}/performance`. Rate limits are not
documented, so a sync pauses between calls and stops at its limit.
ASSUMPTION A-069: a pause of one second is polite enough.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eulerlab.paths import data_path

BASE_URL = "https://quantpedia.com/api/v1"
LANDING = data_path("landing/quantpedia")
TIMEOUT_SECONDS = 30
PAUSE_SECONDS = 1.0
DEFAULT_LIMIT = 50
WORD = re.compile(r"[a-z][a-z0-9\-]{2,}")

Fetch = Callable[[str], bytes]


class NoCredentials(RuntimeError):
    pass


@dataclass(frozen=True)
class Lead:
    id: str
    name: str
    score: float
    sharpe_paper: float | None
    sharpe_recalculated: float | None
    markets: str
    paper: str
    path: str


def credentials() -> tuple[str, str]:
    from eulerlab.env import load_env

    load_env()
    user = os.environ.get("QUANTPEDIA_USERNAME", "").strip()
    key = os.environ.get("QUANTPEDIA_API_KEY", "").strip()
    if not user or not key:
        msg = "QUANTPEDIA_USERNAME and QUANTPEDIA_API_KEY are not set in .env"
        raise NoCredentials(msg)
    return user, key


def http_fetch(path: str) -> bytes:
    user, key = credentials()
    token = base64.b64encode(f"{user}:{key}".encode()).decode()
    request = urllib.request.Request(
        f"{BASE_URL}/{path.lstrip('/')}",
        headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body: bytes = response.read()
    return body


def _land(day_dir: Path, name: str, url: str, body: bytes) -> Path:
    """Write a response once, with its manifest line. An existing file is left alone."""
    target = day_dir / name
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    row = {
        "path": str(target.relative_to(day_dir.parent)),
        "url": url,
        "sha256": hashlib.sha256(body).hexdigest(),
        "knowledge_time": datetime.now(UTC).isoformat(timespec="seconds"),
        "bytes": len(body),
    }
    with (day_dir.parent / "manifest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    return target


def landed_ids(landing: Path | None = None) -> set[str]:
    landing = landing or LANDING
    return {p.stem for p in landing.glob("*/strategy/*.json")}


def sync(
    *,
    limit: int = DEFAULT_LIMIT,
    fetch: Fetch | None = None,
    landing: Path | None = None,
    now: datetime | None = None,
    pause: float = PAUSE_SECONDS,
) -> dict[str, Any]:
    """Land today's strategy list, then details for up to `limit` strategies not landed yet."""
    landing = landing or LANDING
    fetch = fetch or http_fetch
    day = (now or datetime.now(UTC)).date().isoformat()
    day_dir = landing / day
    try:
        listing_path = day_dir / "strategies.json"
        if listing_path.exists():
            listing = json.loads(listing_path.read_text(encoding="utf-8"))
        else:
            body = fetch("strategy")
            listing = json.loads(body)
            _land(day_dir, "strategies.json", f"{BASE_URL}/strategy", body)
    except NoCredentials as exc:
        return {"ok": False, "error": str(exc), "landed": 0}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "error": f"strategy list: {type(exc).__name__}: {exc}"[:300],
            "landed": 0,
        }
    have = landed_ids(landing)
    wanted = [str(s.get("id")) for s in listing if isinstance(s, dict) and s.get("id") is not None]
    todo = [i for i in wanted if i not in have][: max(limit, 0)]
    landed, failed = 0, []
    for ident in todo:
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", ident):
            failed.append(f"{ident}: not a plain id")
            continue
        try:
            body = fetch(f"strategy/{ident}")
            json.loads(body)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            failed.append(f"{ident}: {type(exc).__name__}")
            continue
        _land(day_dir, f"strategy/{ident}.json", f"{BASE_URL}/strategy/{ident}", body)
        landed += 1
        if pause:
            time.sleep(pause)
    return {
        "ok": True,
        "listed": len(wanted),
        "landed": landed,
        "remaining": max(len(wanted) - len(have) - landed, 0),
        "failed": failed,
    }


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_text(v) for v in value)
    if isinstance(value, dict):
        return str(value.get("name") or value.get("title") or "")
    return "" if value is None else str(value)


def catalogue(landing: Path | None = None) -> list[dict[str, Any]]:
    """Every landed strategy detail, newest landing of each id, as plain fields."""
    landing = landing or LANDING
    newest: dict[str, Path] = {}
    for path in sorted(landing.glob("*/strategy/*.json")):
        newest[path.stem] = path
    out: list[dict[str, Any]] = []
    for ident, path in sorted(newest.items()):
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(spec, dict):
            continue
        paper = spec.get("sourcePaper") or {}
        out.append(
            {
                "id": ident,
                "name": str(spec.get("name") or ident),
                "description": str(spec.get("description") or ""),
                "keywords": _text(spec.get("keywords")),
                "markets": _text(spec.get("instruments")) or _text(spec.get("marketFactors")),
                "regions": _text(spec.get("regions")),
                "sharpe_paper": _number((spec.get("paperMetrics") or {}).get("sharpeRatio")),
                "sharpe_recalculated": _number(
                    (spec.get("calculatedMetrics") or {}).get("sharpeRatioInception")
                ),
                "transaction_costs": _text(spec.get("transactionCostsNotes"))
                or _text(spec.get("transactionCosts")),
                "fundamental_reason": _text(spec.get("fundamentalReason")),
                "paper": str(paper.get("name") or "") if isinstance(paper, dict) else "",
                "abstract": str(paper.get("abstract") or "") if isinstance(paper, dict) else "",
                "path": str(path),
            }
        )
    return out


def _words(text: str) -> frozenset[str]:
    return frozenset(WORD.findall(text.lower()))


def leads(topic: str, entries: list[dict[str, Any]], limit: int = 5) -> list[Lead]:
    """Landed strategies closest to a topic, by word overlap with name, keywords and description."""
    want = _words(topic)
    if not want:
        return []
    scored: list[Lead] = []
    for e in entries:
        have = _words(f"{e['name']} {e['keywords']} {e['markets']} {e['description'][:600]}")
        hits = len(want & have)
        if not hits:
            continue
        scored.append(
            Lead(
                id=e["id"],
                name=e["name"],
                score=round(hits / len(want), 3),
                sharpe_paper=e["sharpe_paper"],
                sharpe_recalculated=e["sharpe_recalculated"],
                markets=e["markets"],
                paper=e["paper"],
                path=e["path"],
            )
        )
    scored.sort(key=lambda lead: (-lead.score, lead.id))
    return scored[:limit]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantpedia-sync", description=__doc__)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)
    result = sync(limit=args.limit)
    if not result["ok"]:
        print(f"quantpedia: {result['error']}")
        return 1
    print(
        f"quantpedia: {result['listed']} listed, {result['landed']} landed now, "
        f"{result['remaining']} still to land"
        + (f", {len(result['failed'])} failed" if result["failed"] else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
