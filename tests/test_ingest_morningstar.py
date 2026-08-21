"""Parsing Morningstar's ratings table, and refusing to join it dishonestly.

Two failures shaped these tests, both found by running the scraper rather than
reading it: the pager was clicked by a fixed control id that meant "page 2", so
the crawl re-served the same page forever and stopped at 400 of 5,741 rows; and
an unrated fund was stored as zero stars, which is not a point on Morningstar's
scale.
"""

from __future__ import annotations

from dataclasses import dataclass

from eulerlab.ingest import morningstar

ROW = """
<tr class="mds-data-table__row">
  <td class="mds-data-table__cell">
    <a class="identity-cell-value" href='/mutualfunds/f00000pdux/dsp-large/x.aspx'
       title='DSP Large &amp; Mid Cap Fund Direct Plan Growth'>DSP</a>
  </td>
  <td class="mds-data-table__cell"><span class="tiles-label">Category : </span>Large &amp; Mid- Cap</td>
  <td class="mds-data-table__cell">
    <span class="tiles-label">Medalist Rating : </span>
    <span class='analyst-rating-icon-bronze' title='Bronze'></span>
  </td>
  <td class="mds-data-table__cell"><img src='/images/stylesmall_new2.gif' /></td>
  <td class="mds-data-table__cell"><img src='/images/stylesmall_new0.gif' /></td>
  <td class="mds-data-table__cell" title='Star Rating 3'><img alt='Star Rating 3' /></td>
  <td class="mds-data-table__cell"><span class="tiles-label">Medalist Rating Date : </span>Aug 20, 2026</td>
</tr>
"""

UNRATED = ROW.replace("Star Rating 3", "Star Rating 0").replace("f00000pdux", "f00000zzzz")

PAGER = """
<a href="javascript:__doPostBack(&#39;ctl00$Content$pager$ctl02$ctl01&#39;,&#39;&#39;)">2</a>
<a href="javascript:__doPostBack(&#39;ctl00$Content$pager$ctl03$ctl00&#39;,&#39;&#39;)">Next &gt;</a>
<a href="javascript:__doPostBack(&#39;ctl00$Content$pager$ctl04$ctl00&#39;,&#39;&#39;)">Last &gt;&gt;</a>
"""


def test_ratings_come_from_icons_not_text() -> None:
    """The cell's text is empty — the values live in a class and a title. This
    is why the previous scraper's few rows were useless even where it had them.
    """
    rating = morningstar.parse_page(ROW)[0]
    assert rating.morningstar_id == "f00000pdux"
    assert rating.medalist == "Bronze"
    assert rating.star_rating == 3
    assert rating.equity_stylebox == 2
    assert rating.fixed_income_stylebox == 0
    assert rating.rating_date is not None
    assert rating.rating_date.isoformat() == "2026-08-20"


def test_an_unrated_fund_is_none_not_zero_stars() -> None:
    """Morningstar's scale is 1-5. The page renders unrated as "Star Rating 0",
    and storing that as 0 makes "nobody rated this" indistinguishable from
    "rated worst" — 405 funds were affected on the first full crawl."""
    rating = morningstar.parse_page(UNRATED)[0]
    assert rating.star_rating is None


def test_the_next_link_is_found_by_label_not_by_control_id() -> None:
    """The regression that cost a crawl. `ctl02$ctl01` is the literal "2" link;
    clicking it repeatedly re-serves page 2 and the run stalls at 400 rows."""
    target = morningstar.next_target(PAGER)
    assert target.endswith("ctl03$ctl00")
    assert "ctl02" not in target


def test_the_last_page_reports_no_next_target() -> None:
    """An empty string is a real end condition, and the crawler stops on it
    rather than clicking whatever else is nearby."""
    assert morningstar.next_target("<a>nothing here</a>") == ""


def test_a_page_with_no_rows_parses_as_empty() -> None:
    assert morningstar.parse_page("<html><body>no table</body></html>") == []


# --- the join --------------------------------------------------------------


@dataclass(frozen=True)
class _Scheme:
    scheme_code: str
    name: str
    isin_growth: str = ""
    isin_reinvest: str = ""
    plan: str = ""
    option: str = ""


def _rating(mid: str, name: str) -> morningstar.Rating:
    return morningstar.Rating(
        morningstar_id=mid,
        name=name,
        category="",
        medalist="",
        star_rating=None,
        equity_stylebox=None,
        fixed_income_stylebox=None,
        rating_date=None,
        detail_path=f"/mutualfunds/{mid}/x/morningstar-analysis.aspx",
    )


def test_the_isin_is_read_from_the_fund_page() -> None:
    """The listing page carries no ISIN, which is what forced the fuzzy name
    join and capped it at 18.3%. The fund's own page carries one."""
    assert morningstar.parse_isin("<div>ISIN INF740K01PM4 blah</div>") == "INF740K01PM4"
    assert morningstar.parse_isin("<div>nothing here</div>") == ""


def test_an_isin_match_beats_the_name_and_is_exact() -> None:
    join = morningstar.join_to_amfi(
        [_rating("f1", "Totally Different Name")],
        [_Scheme("119219", "DSP Large & Mid Cap Fund", isin_growth="INF740K01PL6")],
        isins={"f1": "INF740K01PL6"},
    )
    assert join.matched == {"f1": "INF740K01PL6"}
    assert join.by_isin == 1


def test_two_isins_of_one_scheme_are_two_instruments_not_a_collision() -> None:
    """The correction that unlocked the join.

    AMFI publishes two ISINs per scheme_code — payout and reinvestment — while
    Morningstar treats them as separate funds. Joining on scheme_code made both
    ratings collide on one key and the one-to-one guard dropped both. They were
    never contested: they are two instruments inside one scheme, and the ISIN
    is the instrument.
    """
    scheme = _Scheme(
        "119219",
        "DSP Large & Mid Cap Fund",
        isin_growth="INF740K01PM4",
        isin_reinvest="INF740K01PN2",
    )
    join = morningstar.join_to_amfi(
        [_rating("f1", "DSP Payout"), _rating("f2", "DSP Reinvestment")],
        [scheme],
        isins={"f1": "INF740K01PM4", "f2": "INF740K01PN2"},
    )
    assert len(join.matched) == 2
    assert join.ambiguous == 0
    assert join.matched["f1"] != join.matched["f2"]


def test_an_unknown_name_with_no_isin_is_reported_not_dropped() -> None:
    join = morningstar.join_to_amfi([_rating("f1", "Nonexistent Fund")], [_Scheme("1", "Other")])
    assert join.unmatched == 1
    assert join.rate == 0.0


def test_amfi_is_the_spine_and_unrated_schemes_survive() -> None:
    """Every AMFI scheme appears once whether or not a rating was found.
    Morningstar as the spine would silently shrink the universe to whatever a
    third party happens to cover."""
    schemes = [
        _Scheme("1", "Rated Fund", isin_growth="INF000000001"),
        _Scheme("2", "Unrated Fund", isin_growth="INF000000002"),
    ]
    ratings = [_rating("f1", "Rated Fund")]
    join = morningstar.Join(matched={"f1": "INF000000001"}, ambiguous=0, unmatched=0, by_isin=1)

    rows = morningstar.enrich(schemes, ratings, join, isins={"f1": "INF000000001"})
    assert len(rows) == 2
    by_isin = {r["isin"]: r for r in rows}
    assert by_isin["INF000000001"]["rating_join"] == "isin"
    assert by_isin["INF000000002"]["rating_join"] == "none"
    assert by_isin["INF000000002"]["star_rating"] is None


def test_a_fund_page_is_reachable_by_id_alone() -> None:
    """The slug in the URL is decorative — the id resolves the fund.

    This is what let the ISIN crawl be driven from a landed snapshot instead of
    re-walking the listing, whose pagination completed all 29 pages once and
    stalled at page 4 the next time. A crawl that depends on a flaky crawl
    inherits its flakiness.
    """
    rating = _rating("f00000pduy", "Some Fund")
    assert rating.path.startswith("/mutualfunds/f00000pduy/")

    without = morningstar.Rating(
        morningstar_id="f00000pduy",
        name="Some Fund",
        category="",
        medalist="",
        star_rating=None,
        equity_stylebox=None,
        fixed_income_stylebox=None,
        rating_date=None,
    )
    assert without.path == "/mutualfunds/f00000pduy/x/morningstar-analysis.aspx"


def test_every_isin_of_a_scheme_gets_its_own_row() -> None:
    """The enriched output is at the INSTRUMENT grain, not the scheme grain.

    Emitting one row per scheme keyed on isin_growth silently dropped every
    rating matched to a scheme's reinvestment ISIN — 1,727 of 4,845 successful
    matches went nowhere, and the loss was invisible because the rows that did
    appear looked correct.
    """
    scheme = _Scheme(
        "119219",
        "DSP Large & Mid Cap Fund",
        isin_growth="INF740K01PM4",
        isin_reinvest="INF740K01PN2",
    )
    ratings = [_rating("f1", "DSP Payout"), _rating("f2", "DSP Reinvestment")]
    join = morningstar.Join(
        matched={"f1": "INF740K01PM4", "f2": "INF740K01PN2"},
        ambiguous=0,
        unmatched=0,
        by_isin=2,
    )
    rows = morningstar.enrich(
        [scheme], ratings, join, isins={"f1": "INF740K01PM4", "f2": "INF740K01PN2"}
    )

    assert len(rows) == 2, "one row per ISIN, not one per scheme"
    assert {r["isin"] for r in rows} == {"INF740K01PM4", "INF740K01PN2"}
    # Both matches attach; neither is dropped.
    assert all(r["rating_join"] == "isin" for r in rows)
    assert {r["morningstar_id"] for r in rows} == {"f1", "f2"}


def test_a_scheme_with_one_isin_yields_one_row() -> None:
    scheme = _Scheme("1", "Single ISIN Fund", isin_growth="INF000000001")
    rows = morningstar.enrich([scheme], [], morningstar.Join(matched={}, ambiguous=0, unmatched=0))
    assert len(rows) == 1
    assert rows[0]["isin_variant"] == "growth/payout"
