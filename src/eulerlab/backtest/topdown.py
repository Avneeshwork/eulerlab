"""Top-down ranking: the strongest sectors, then the strongest industries in them (research 182).

Moskowitz and Grinblatt (1999) find industry momentum explains much of stock
momentum; Sehgal and Jain (2011) find sector momentum in India, 6-month
formation stronger than 12. The rule here was fixed before any run:

- a sector's (or industry's) score is the equal-weighted mean 126-session
  return of its members among the stocks given (the liquid 250 on the day);
- a group counts only with 3 or more members; an industry with fewer inherits
  its sector's score, so a small industry is judged by its sector rather than
  dropped (decided before running, research 182 results);
- the top 5 sectors are kept; inside them, industries scoring above the median
  scored industry of the whole universe.

Sector tags are today's (`fundamentals.sectors`), applied backwards: a stated
bias (A-128). Everything else comes from the view, so it holds only the past.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import median

from eulerlab.backtest.strategy import MarketView
from eulerlab.fundamentals import sectors

FORMATION = 126
TOP_SECTORS = 5
MIN_MEMBERS = 3


@dataclass(frozen=True)
class Ranking:
    """One day's top-down view of the stocks given."""

    sector_of: dict[str, str]
    industry_of: dict[str, str]
    sector_score: dict[str, float]
    industry_score: dict[str, float]
    top_sectors: tuple[str, ...]
    strong_industries: frozenset[str]

    def in_top_sectors(self, symbol: str) -> bool:
        return self.sector_of.get(symbol, "") in self.top_sectors

    def passes(self, symbol: str) -> bool:
        """In a top sector and in an industry above the median industry."""
        return (
            self.in_top_sectors(symbol)
            and self.industry_of.get(symbol, "") in self.strong_industries
        )


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def formation_return(closes: Sequence[float], n: int = FORMATION) -> float | None:
    if len(closes) < n + 1 or closes[-n - 1] <= 0:
        return None
    return closes[-1] / closes[-n - 1] - 1.0


def rank(
    view: MarketView,
    names: Sequence[str],
    tags: Mapping[str, sectors.Tag] | None = None,
    *,
    top: int = TOP_SECTORS,
) -> Ranking:
    """Score sectors and industries over `names` on `view` and pick the strong ones."""
    tag_of = sectors.load() if tags is None else tags
    sector_of: dict[str, str] = {}
    industry_of: dict[str, str] = {}
    ret: dict[str, float] = {}
    for s in names:
        rows = view.history.get(s) or []
        if not rows:
            continue
        tag = tag_of.get(rows[-1].isin)
        if tag is None or not tag.sector:
            continue
        r = formation_return([x.close for x in rows])
        if r is None:
            continue
        sector_of[s] = tag.sector
        # Industry names repeat across sectors rarely, but key on both to be safe.
        industry_of[s] = f"{tag.sector} / {tag.industry or tag.sector}"
        ret[s] = r
    by_sector: dict[str, list[float]] = {}
    by_industry: dict[str, list[float]] = {}
    for s, r in ret.items():
        by_sector.setdefault(sector_of[s], []).append(r)
        by_industry.setdefault(industry_of[s], []).append(r)
    sector_score = {k: _mean(v) for k, v in by_sector.items() if len(v) >= MIN_MEMBERS}
    scored_industries = {k: _mean(v) for k, v in by_industry.items() if len(v) >= MIN_MEMBERS}
    industry_score = dict(scored_industries)
    for s in ret:
        ind, sec = industry_of[s], sector_of[s]
        if ind not in industry_score and sec in sector_score:
            industry_score[ind] = sector_score[sec]
    top_sectors = tuple(sorted(sector_score, key=lambda k: (-sector_score[k], k))[:top])
    bar = median(scored_industries.values()) if scored_industries else 0.0
    strong = frozenset(k for k, v in industry_score.items() if v > bar)
    return Ranking(sector_of, industry_of, sector_score, industry_score, top_sectors, strong)
