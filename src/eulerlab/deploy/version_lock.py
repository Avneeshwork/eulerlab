"""The strategy version lock: a deployment trades the code it was deployed with (ADR-087).

On a deployment's first run the fingerprint of its strategy's own source —
the builder and the class it builds, the intraday signal, the study module or
the overnight book — is written to `version_lock.json` in its folder. Every
later run compares. When the code has changed:

- **paper** — the run goes ahead and its state carries a warning, so the page
  and Telegram say the book is no longer trading what was deployed;
- **live** — the run stops before anything is sent.

The fingerprint covers only the strategy's own source, not the engine or the
OMS: an engine fix is tested by `make verify` across every strategy, while a
strategy edit changes what one deployment means. Re-locking after reviewing a
change is the operator's command: `make relock DEPLOYMENT=<id>`.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FILE = "version_lock.json"


@dataclass(frozen=True)
class Check:
    locked: str
    current: str
    status: str
    """locked-now · same · changed · unavailable"""
    detail: str = ""

    @property
    def changed(self) -> bool:
        return self.status == "changed"


_ADDRESS = re.compile(r" at 0x[0-9a-fA-F]+")


def _stable(text: str) -> str:
    """`text` without memory addresses. The repr of a function or object held
    by a strategy carries one ("<function momentum_12_1 at 0x7f60...>"), which
    differs every time Python starts, so the fingerprint did too (HISTORY #63)."""
    return _ADDRESS.sub("", text)


def _source(obj: Any) -> str:
    try:
        return inspect.getsource(obj)
    except (OSError, TypeError):
        return ""


def sources(strategy_id: str) -> list[str]:
    """The source text that defines one strategy, in a fixed order."""
    from eulerlab.deploy import overnight, study_book
    from eulerlab.intraday.paper_scan import ALL_SIGNALS

    if strategy_id in overnight.STRATEGIES:
        return [_source(overnight)]
    if strategy_id in ALL_SIGNALS:
        signal = ALL_SIGNALS[strategy_id]
        detect = getattr(signal, "detect", None)
        return [
            _source(detect) if detect is not None else "",
            _source(type(signal)),
            _stable(repr(signal)),
        ]
    from eulerlab import forward
    from eulerlab.deploy import rule_book

    if rule_book.is_rule(strategy_id):
        # A gated intraday rule: its card and the book that applies it (ADR-142).
        path = forward.card_path(strategy_id)
        card = path.read_text(encoding="utf-8") if path.exists() else ""
        if strategy_id not in rule_book.RULES:  # an engine card (ADR-150)
            from eulerlab.deploy import engine_book
            from eulerlab.intraday import rule_engine

            return [card, _source(engine_book), _source(rule_engine), _source(rule_book)]
        return [card, _source(rule_book.RULES[strategy_id]), _source(rule_book)]
    if forward.is_hypothesis(strategy_id):
        # A promoted card: its text (what was gated) and the code that trades it.
        path = forward.card_path(strategy_id)
        card = path.read_text(encoding="utf-8") if path.exists() else ""
        from eulerlab.backtest.strategies import RankAndHold

        return [card, _source(RankAndHold), _source(forward.GatedCard)]
    name = study_book.module_of(strategy_id)
    if name is not None:
        import importlib

        return [_source(importlib.import_module(f"eulerlab.strategies.studies.{name}"))]
    from eulerlab.strategies.daily.published import BUILDERS

    builder = BUILDERS.get(strategy_id)
    if builder is None:
        return []
    texts = [_source(builder)]
    try:
        built = builder()
        texts += [
            _source(type(built)),
            _stable(repr(sorted(vars(built).items()))) if hasattr(built, "__dict__") else "",
        ]
    except Exception as exc:  # a builder that fails is reported by the runner itself
        texts.append(f"builder failed: {type(exc).__name__}")
    return texts


def fingerprint(strategy_id: str) -> str:
    texts = sources(strategy_id)
    if not any(texts):
        return ""
    return hashlib.sha256("\n\x00".join(texts).encode()).hexdigest()


def check(folder: Path, strategy_id: str, *, current: str | None = None) -> Check:
    """Compare with the lock, writing it if there is none yet."""
    now = fingerprint(strategy_id) if current is None else current
    if not now:
        return Check("", "", "unavailable", "the strategy's source could not be read")
    path = folder / FILE
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "strategy": strategy_id,
                    "fingerprint": now,
                    "locked_at": datetime.now(UTC).isoformat(timespec="seconds"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return Check(now, now, "locked-now")
    locked = str(json.loads(path.read_text(encoding="utf-8")).get("fingerprint", ""))
    if locked == now:
        return Check(locked, now, "same")
    return Check(
        locked,
        now,
        "changed",
        f"{strategy_id}'s code changed since it was deployed (lock {locked[:10]}, now {now[:10]}). "
        f"Review the change, then `make relock DEPLOYMENT={folder.name}`.",
    )


def relock(folder: Path, strategy_id: str, note: str) -> str:
    if not note.strip():
        msg = "say why the new code is accepted"
        raise ValueError(msg)
    now = fingerprint(strategy_id)
    path = folder / FILE
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    history = (
        [
            *(previous.get("history") or []),
            {k: previous.get(k) for k in ("fingerprint", "locked_at")},
        ]
        if previous
        else []
    )
    path.write_text(
        json.dumps(
            {
                "strategy": strategy_id,
                "fingerprint": now,
                "locked_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "note": note.strip(),
                "history": history,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return now


def main(argv: Sequence[str] | None = None) -> int:
    from eulerlab.deploy import deployments

    parser = argparse.ArgumentParser(prog="relock", description=__doc__)
    parser.add_argument("deployment")
    parser.add_argument("--note", required=True)
    args = parser.parse_args(argv)
    deployment = deployments.load(args.deployment)
    now = relock(deployment.folder, deployment.strategy_id, args.note)
    print(f"{deployment.id}: locked to {now[:12]} ({args.note})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
