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
    )


def test_a_clean_name_match_joins() -> None:
    join = morningstar.join_to_amfi(
        [_rating("f1", "DSP Large & Mid Cap Fund Direct Plan Growth")],
        [_Scheme("119551", "DSP Large & Mid Cap Fund")],
    )
    assert join.matched == {"f1": "119551"}
    assert join.rate == 1.0


def test_an_ambiguous_name_is_left_unjoined() -> None:
    """The rule that matters. Two schemes folding to the same name means the
    join cannot say which one — and a rating on the wrong fund is worse than a
    rating on none, so neither is chosen."""
    join = morningstar.join_to_amfi(
        [_rating("f1", "Axis Bluechip Fund Direct Plan Growth")],
        [_Scheme("1", "Axis Bluechip Fund"), _Scheme("2", "Axis Bluechip Fund")],
    )
    assert join.matched == {}
    assert join.ambiguous == 1


def test_an_unknown_name_is_reported_not_dropped() -> None:
    join = morningstar.join_to_amfi([_rating("f1", "Nonexistent Fund")], [_Scheme("1", "Other")])
    assert join.unmatched == 1
    assert join.rate == 0.0
