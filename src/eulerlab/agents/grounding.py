"""Is every number and name in a model's answer in what it was given? Checked by code (ADR-088).

A model that checks its own answer without outside evidence does not get
more accurate (Huang et al. 2023, research 126). So the check here reads the
evidence, not the model: the tool results the knowledge agent received, or the
brief the market brief's commentary was written under.

What is checked, in the answer outside its "Sources:" part:

- **numbers** — any with a decimal point, a thousands comma or a percent sign,
  and any whole number of two digits or more. A number counts as supported
  when the evidence holds the same value, or a value that rounds to it at the
  answer's precision, or the same share written as a fraction (12% for 0.12).
- **ids and paths** — `H-0001`, `ADR-084`, `T-4170`, `A-066`, `S-041`, and
  file paths ending .md, .yaml, .py or .json.

Single digits are not checked: list numbers and "two of three" would make
every answer fail, and a wrong single digit is the case this misses.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

NUMBER = re.compile(r"(?<![\w.\-/])-?\d[\d,]*(?:\.\d+)?%?(?![\w])")
IDENT = re.compile(r"\b(?:H|ADR|T|A|S)-\d{3,4}\b")
PATH = re.compile(r"\b[\w\-./]+\.(?:md|yaml|py|json)\b")
SOURCES = re.compile(r"^\s*sources(?:\s*\([^)]*\))?\s*:", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class Grounding:
    checked: int
    unsupported: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unsupported


def body_of(answer: str) -> str:
    """The answer without its Sources part, which only names where it looked."""
    found = SOURCES.search(answer)
    return answer[: found.start()] if found else answer


def _value(token: str) -> tuple[float, int, bool] | None:
    raw = token.replace(",", "")
    percent = raw.endswith("%")
    raw = raw.rstrip("%")
    try:
        value = float(raw)
    except ValueError:
        return None
    decimals = len(raw.split(".", 1)[1]) if "." in raw else 0
    return value, decimals, percent


def _worth_checking(token: str) -> bool:
    if any(c in token for c in ".,%"):
        return True
    digits = token.lstrip("-")
    return len(digits) >= 2


def _supported(token: str, evidence_values: list[float]) -> bool:
    parsed = _value(token)
    if parsed is None:
        return True
    value, decimals, percent = parsed
    candidates = [(value, decimals)] + ([(value / 100, decimals + 2)] if percent else [])
    for seen in evidence_values:
        for want, places in candidates:
            if round(seen, places) == round(want, places):
                return True
    return False


def check(answer: str, evidence: Iterable[str], question: str = "") -> Grounding:
    text = body_of(answer)
    pool = "\n".join([*evidence, question])
    pool_lower = pool.lower()
    values = [p[0] for p in (_value(t) for t in NUMBER.findall(pool)) if p is not None]
    unsupported: list[str] = []
    checked = 0
    names = [*IDENT.findall(text), *PATH.findall(text)]
    bare = IDENT.sub(" ", PATH.sub(" ", text))
    for token in NUMBER.findall(bare):
        if not _worth_checking(token):
            continue
        checked += 1
        if token not in pool and not _supported(token, values) and token not in unsupported:
            unsupported.append(token)
    for token in names:
        checked += 1
        if token.lower() not in pool_lower and token not in unsupported:
            unsupported.append(token)
    return Grounding(checked, unsupported)


def prompt_version(*parts: str) -> str:
    """A short fingerprint of the instructions a model ran under, kept with each output."""
    return hashlib.sha256("\n\x00".join(parts).encode()).hexdigest()[:12]
