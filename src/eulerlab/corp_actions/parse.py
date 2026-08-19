"""Turn one NSE `subject` string into typed corporate-action components.

The feed gives no structured ratio or amount — only free text like
``"Bonus 1:1 / Face Value Split From Rs 10/- Per Share To Rs 2/- Per Share"``.
A single row routinely bundles more than one action on the same ex-date, so
parsing has two steps: split the subject into its component clauses, then
classify and extract each clause on its own.

What is deliberately **not** guessed: if a clause is recognisably a bonus,
split, rights issue or dividend but the numbers inside it do not match any
known phrasing, it comes back as `UNPARSED` with the raw text attached rather
than silently dropped or defaulted to 1:1. A wrong ratio would misprice every
position that ever held the instrument; a missing one only misses a data
point, and the caller can see it in `unparsed_count`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

# Split on "/" whenever it is followed by the start of a new capitalised
# clause, whether or not NSE put spaces around it — both "1:1 / Face Value"
# and "Meeting/Dividend" appear in the wild. A "/" inside "Rs 10/-" is never
# followed by an uppercase letter, so currency shorthand is never split.
_SEGMENT_SPLIT = re.compile(r"\s*/\s*(?=[A-Z])|\s+[Aa]nd\s+")

_BONUS_RATIO = re.compile(r"Bonus\s*-?\s*:?\s*(\d+)\s*:\s*(\d+)", re.IGNORECASE)
_RIGHTS_RATIO = re.compile(r"Rights\s*:?\s*(\d+)\s*:\s*(\d+)", re.IGNORECASE)
_RIGHTS_PREMIUM = re.compile(r"Premium\s*Rs\.?\s*([\d.]+)", re.IGNORECASE)
_SPLIT_VALUES = re.compile(
    r"(?:Rs|Re)\.?\s*([\d.]+).*?\bTo\b.*?(?:Rs|Re)\.?\s*([\d.]+)", re.IGNORECASE | re.DOTALL
)
# "Rs", "Rs.", "Rs-", "Rs -" all appear for the same thing; "Per Share" is not
# required, since "Final Dividend - Rs 15/-" is real observed data.
_DIVIDEND_AMOUNT = re.compile(r"(?:Rs|Re)\.?\s*-?\s*([\d.]+)", re.IGNORECASE)
# Fallback for the rarer case where NSE dropped the currency prefix entirely
# ("Dividend - 1.40 Per Share") but "Per Share" survived, which is enough to
# say the number in front of it is the amount.
_DIVIDEND_AMOUNT_NO_PREFIX = re.compile(r"([\d.]+)\s*/?-?\s*Per\s*Share", re.IGNORECASE)


class Kind(StrEnum):
    DIVIDEND = "dividend"
    BONUS = "bonus"
    SPLIT = "split"
    """Face-value change, aka sub-division."""
    RIGHTS = "rights"
    BUYBACK = "buyback"
    DEMERGER = "demerger"
    """Informational only. Sprint 3's succession model is the source of truth
    for demerger ratios; this is not folded into the adjustment engine."""
    MEETING = "meeting"
    """AGM/EGM/postal-ballot notices with no price effect on their own."""
    UNPARSED = "unparsed"
    """A recognised, price-relevant kind whose numbers did not parse."""
    OTHER = "other"


@dataclass(frozen=True)
class ParsedComponent:
    """One action extracted from one clause of one subject line."""

    kind: Kind
    raw: str
    ratio_new: int | None = None
    """Bonus/rights: units issued per `ratio_held` already-held units."""
    ratio_held: int | None = None
    rights_premium: float | None = None
    face_value_from: float | None = None
    face_value_to: float | None = None
    dividend_amount: float | None = None

    @property
    def bonus_split_multiplier(self) -> float | None:
        """How many post-action units one pre-action unit becomes.

        Bonus 1:2 => 1 new share per 2 held => 3 units for every 2 =>
        multiplier 1.5. A split from face value 10 to 2 multiplies units by
        10/2 = 5. Returns None for anything that is not a bonus or split, or
        whose numbers did not parse.
        """
        if self.kind is Kind.BONUS and self.ratio_new is not None and self.ratio_held:
            return (self.ratio_held + self.ratio_new) / self.ratio_held
        if self.kind is Kind.SPLIT and self.face_value_from is not None and self.face_value_to:
            return self.face_value_from / self.face_value_to
        return None

    def rights_multiplier(self, *, cum_price: float, face_value: float | None) -> float | None:
        """`P / TERP` — the same "divide old prices by it" sense as above.

        A rights issue is not free, so unlike a bonus its dilution cannot be
        read off the ratio: it depends how far below market the issue price
        sits. The theoretical ex-rights price is

            TERP = (B*P + A*S) / (A + B)

        for entitlement A:B at issue price S with cum price P. NSE states the
        same thing as `(P-E)/P`; the two are algebraically identical, and
        research note 010 shows the expansion. Note NSE's factor is the
        *reciprocal* of this one — theirs is <= 1 and multiplies, ours is >= 1
        and divides, matching `bonus_split_multiplier`. Mixing the two senses
        inverts the adjustment, which is why only one convention is used here.

        `S` is face value plus premium, an Indian-market convention validated
        against Reliance's 2020 issue (research note 010).

        Returns None when the numbers are missing, or when `S >= P`: rights
        priced at or above market confer no benefit, nobody subscribes, and
        NSE makes no adjustment. Producing a factor there would adjust prices
        the wrong way.
        """
        if self.kind is not Kind.RIGHTS:
            return None
        if self.ratio_new is None or not self.ratio_held:
            return None
        if self.rights_premium is None or face_value is None:
            return None
        issue_price = face_value + self.rights_premium
        if issue_price >= cum_price or cum_price <= 0:
            return None
        terp = (self.ratio_held * cum_price + self.ratio_new * issue_price) / (
            self.ratio_held + self.ratio_new
        )
        if terp <= 0:
            return None
        return cum_price / terp


def _to_float(text: str) -> float | None:
    """NSE's own data is occasionally malformed (`"62..50"` was observed live).

    A double decimal point has only one sane reading — collapsing it is
    fixing a typo, not guessing a value. Anything else that still fails to
    parse comes back as UNPARSED so it is counted rather than mispriced.
    """
    try:
        return float(re.sub(r"\.{2,}", ".", text))
    except ValueError:
        return None


def _classify_clause(clause: str) -> ParsedComponent:
    upper = clause.upper()

    if "BONUS" in upper:
        m = _BONUS_RATIO.search(clause)
        if m:
            return ParsedComponent(
                Kind.BONUS, clause, ratio_new=int(m.group(1)), ratio_held=int(m.group(2))
            )
        return ParsedComponent(Kind.UNPARSED, clause)

    if "RIGHTS" in upper:
        m = _RIGHTS_RATIO.search(clause)
        if m:
            premium_m = _RIGHTS_PREMIUM.search(clause)
            at_par = "AT PAR" in upper
            premium = 0.0 if at_par else (_to_float(premium_m.group(1)) if premium_m else None)
            return ParsedComponent(
                Kind.RIGHTS,
                clause,
                ratio_new=int(m.group(1)),
                ratio_held=int(m.group(2)),
                rights_premium=premium,
            )
        return ParsedComponent(Kind.UNPARSED, clause)

    if "FACE VALUE" in upper or "SUB-DIVISION" in upper or "SUBDIVISION" in upper:
        m = _SPLIT_VALUES.search(clause)
        if m:
            from_val, to_val = _to_float(m.group(1)), _to_float(m.group(2))
            if from_val is not None and to_val is not None:
                return ParsedComponent(
                    Kind.SPLIT, clause, face_value_from=from_val, face_value_to=to_val
                )
        return ParsedComponent(Kind.UNPARSED, clause)

    if "DIVIDEND" in upper or "INTEREST" in upper or "DISTRIBUTION" in upper:
        m = _DIVIDEND_AMOUNT.search(clause) or _DIVIDEND_AMOUNT_NO_PREFIX.search(clause)
        amount = _to_float(m.group(1)) if m else None
        if amount is not None:
            return ParsedComponent(Kind.DIVIDEND, clause, dividend_amount=amount)
        return ParsedComponent(Kind.UNPARSED, clause)

    if "BUYBACK" in upper or "BUY BACK" in upper:
        return ParsedComponent(Kind.BUYBACK, clause)

    if "DEMERGER" in upper:
        return ParsedComponent(Kind.DEMERGER, clause)

    if any(k in upper for k in ("ANNUAL GENERAL", "EXTRAORDINARY GENERAL", "POSTAL BALLOT")):
        return ParsedComponent(Kind.MEETING, clause)

    return ParsedComponent(Kind.OTHER, clause)


def parse_subject(subject: str) -> list[ParsedComponent]:
    """Split a compound subject into its component actions."""
    clauses = [c.strip() for c in _SEGMENT_SPLIT.split(subject) if c.strip()]
    return [_classify_clause(c) for c in clauses] or [ParsedComponent(Kind.OTHER, subject)]


@dataclass(frozen=True)
class CorporateAction:
    """One row of the feed, resolved to its instrument and its components."""

    isin: str
    symbol: str
    ex_date: date
    components: tuple[ParsedComponent, ...]
    raw_subject: str
    face_value: float | None = None
    """From the feed's `faceVal`. Needed only by rights: the issue price is
    face value plus the stated premium (research note 010)."""

    @property
    def unparsed(self) -> tuple[ParsedComponent, ...]:
        return tuple(c for c in self.components if c.kind is Kind.UNPARSED)


_EX_DATE_FORMATS = ("%d-%b-%Y",)


def _parse_ex_date(raw: str) -> date | None:
    if not raw or raw == "-":
        return None
    for fmt in _EX_DATE_FORMATS:
        try:
            # A calendar date, not an instant - .date() discards whatever
            # naive time strptime attaches, so there is no tz to get wrong.
            return datetime.strptime(raw, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
    return None


def parse_rows(rows: list[dict[str, object]]) -> tuple[list[CorporateAction], int]:
    """Parse every row from a landed year's JSON. Returns (actions, skipped).

    `skipped` counts rows with no ISIN or no parseable exDate — both make a
    row unusable regardless of what its subject says, and are counted rather
    than silently dropped so a build can report them.
    """
    actions: list[CorporateAction] = []
    skipped = 0
    for row in rows:
        isin = str(row.get("isin") or "").strip()
        symbol = str(row.get("symbol") or "").strip()
        ex_date = _parse_ex_date(str(row.get("exDate") or ""))
        subject = str(row.get("subject") or "").strip()
        if not isin or ex_date is None:
            skipped += 1
            continue
        actions.append(
            CorporateAction(
                isin=isin,
                symbol=symbol,
                ex_date=ex_date,
                components=tuple(parse_subject(subject)),
                raw_subject=subject,
                face_value=_to_float(str(row.get("faceVal") or "").strip()),
            )
        )
    return actions, skipped
