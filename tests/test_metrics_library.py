"""The metrics library and the knowledge keeper that keeps it current (ADR-103, ADR-104)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from eulerlab.agents import runtime
from eulerlab.agents.spec import AgentSpec, effective
from eulerlab.agents.workers import knowledge_keeper
from eulerlab.assistant import tools
from eulerlab.ingest.fetch import FetchResult, Outcome
from eulerlab.ingest.landing import Landing
from eulerlab.metrics_library import catalog, gaps, normals, regwatch

SEBI = b"""<?xml version="1.0" encoding="UTF-8" standalone="no"?><rss version="2.0"><channel>
<title>SEBI RSS Feed</title>
<item><title>Revised framework for index derivatives: lot size review</title>
<description>Changes to lot size of index futures and options</description>
<link>https://www.sebi.gov.in/legal/circulars/oct-2026/x_1.html</link><pubDate>30 Oct, 2026 +0530</pubDate></item>
<item><title>Final Order in the matter of ABC Ltd.</title><description>Order</description>
<link>https://www.sebi.gov.in/enforcement/orders/oct-2026/abc_2.html</link><pubDate>29 Oct, 2026 +0530</pubDate></item>
</channel></rss>"""

RBI = (
    '﻿<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>RBI</title>'
    "<item><title><![CDATA[Monetary Policy Statement: repo rate]]></title>"
    "<description><![CDATA[<p>The policy repo rate is kept unchanged.</p>]]></description>"
    "<link>https://rbi.org.in/x?id=1</link><pubDate>Fri, 30 Oct 2026 10:00:00 +0530</pubDate></item>"
    "</channel></rss>"
).encode()


class FakeFetcher:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    def get(self, url: str) -> FetchResult:
        self.calls.append(url)
        if url in self.payloads:
            return FetchResult(Outcome.OK, url, payload=self.payloads[url], status=200)
        return FetchResult(Outcome.FAILED, url, status=503, detail="HTTP 503")


SOURCES = regwatch.Sources(
    feeds=[
        regwatch.Feed(name="sebi", title="SEBI", url="https://example.test/sebi.xml"),
        regwatch.Feed(name="rbi_press", title="RBI", url="https://example.test/rbi.xml"),
    ],
    topics=[
        regwatch.Topic(keywords=["lot size", "derivatives"], pages=["lot-size-and-tick"]),
        regwatch.Topic(keywords=["repo rate"], pages=["rbi-policy-rate"]),
        regwatch.Topic(keywords=["stt"], pages=["capital-gains-and-stt"]),
    ],
)


# --- the library itself --------------------------------------------------------------------------


def test_every_page_has_a_heading_a_one_line_and_resolving_links() -> None:
    pages = catalog.pages()
    assert len(pages) >= 100
    ids = {p.id for p in pages}
    for page in pages:
        assert page.name and page.one_line, page.path
        for target in __import__("re").findall(r"\]\(\.\./([a-z_]+)/([a-z0-9-]+)\.md\)", page.text):
            assert target[1] in ids, (page.id, target)


def test_the_keeper_config_points_only_at_real_pages() -> None:
    ids = {p.id for p in catalog.pages()}
    sources = regwatch.load_sources()
    for topic in sources.topics:
        assert set(topic.pages) <= ids, topic.pages
    spec = yaml.safe_load(Path("config/agents/knowledge_keeper.yaml").read_text())
    for page in spec["options"]["sections"].values():
        assert page == "-" or page in ids, page


def test_find_by_id_name_and_words(tmp_path: Path) -> None:
    assert catalog.find("india-vix")[0].id == "india-vix"
    assert catalog.find("Deflated Sharpe")[0].id == "deflated-sharpe"
    assert any(p.id == "put-call-ratio" for p in catalog.find("put call ratio open interest"))
    assert catalog.find("") == []


def test_a_lookup_with_no_page_is_logged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    misses = tmp_path / "misses.jsonl"
    monkeypatch.setattr(catalog, "MISSES", misses)
    monkeypatch.setattr(catalog, "find", lambda q, root=catalog.ROOT, limit=3: [])
    answer = tools.TOOLS["explain_metric"].run({"metric": "zorbitz ratio"})
    assert "No page" in answer
    rows = [json.loads(x) for x in misses.read_text().splitlines()]
    assert rows[0]["query"] == "zorbitz ratio" and rows[0]["knowledge_time"]


def test_explain_metric_returns_the_page_and_the_live_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = tmp_path / "normals.json"
    normals.save(
        {
            "knowledge_time": "2026-10-31T10:00:00+00:00",
            "metrics": {"india-vix": {"1y": normals.spread([12.0, 13.0, 15.0], "last 252 closes")}},
        },
        live,
    )
    monkeypatch.setattr(normals, "OUT", live)
    monkeypatch.setattr(normals, "load", lambda path=live: json.loads(live.read_text()))
    answer = tools.TOOLS["explain_metric"].run({"metric": "india-vix"})
    assert answer.startswith("Source: docs/METRICS/market/india-vix.md")
    assert "Live normal ranges" in answer and "median 13.0" in answer


# --- normals -------------------------------------------------------------------------------------


def test_spread_is_nearest_rank_with_its_count() -> None:
    out = normals.spread(list(range(1, 101)), "w")
    assert out == {
        "p5": 6.0,
        "p25": 26.0,
        "p50": 51.0,
        "p75": 76.0,
        "p95": 96.0,
        "n": 100,
        "window": "w",
    }
    assert normals.spread([None, None], "w") is None


def test_normals_key_by_page_and_skip_what_is_not_held() -> None:
    out = normals.from_series(
        vix=[10.0, 12.0, 14.0],
        nifty_close=[100.0, 101.0, 99.0],
        nifty_pe_since_2021=[],
        breadth={"above_50": [20.0, 40.0]},
        positioning={"FII": [0.1, 0.12]},
        fii_net=[-1.0, 2.0, -3.0, 4.0, -5.0, 6.0],
        dii_net=[1.0],
        pcr=[],
        atm_iv=[],
    )
    assert set(out["india-vix"]) == {"all", "1y"}
    assert "valuation" not in out and "put-call-ratio" not in out
    assert out["fii-dii-cash-flows"]["fii_net_5d"]["n"] == 2
    assert out["participant-long-share"]["FII"]["p50"] == 12.0


# --- regulator watch -----------------------------------------------------------------------------


def test_parse_reads_sebi_and_rbi_dates_and_strips_markup() -> None:
    sebi = regwatch.parse("sebi", SEBI) or []
    assert [i.published for i in sebi] == ["2026-10-30", "2026-10-29"]
    rbi = regwatch.parse("rbi_press", RBI) or []
    assert (
        rbi[0].published == "2026-10-30"
        and rbi[0].summary == "The policy repo rate is kept unchanged."
    )


def test_parse_refuses_a_doctype_and_non_feeds() -> None:
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss version="2.0"><channel></channel></rss>'
    assert regwatch.parse("x", bomb) is None
    assert regwatch.parse("x", b"<html><body>hi</body></html>") is None
    assert regwatch.parse("x", b"not xml") is None


def test_keywords_match_whole_words_only() -> None:
    item = regwatch.FeedItem("sebi", "Instructions on the first day", "", "", "", "k")
    assert (
        regwatch.link_pages(item, SOURCES.topics) == []
    )  # 'first' contains 'stt'? no; 'instructions' contains 'stt'? no
    sttish = regwatch.FeedItem("sebi", "Investors' settlement", "", "", "", "k")
    assert regwatch.link_pages(sttish, SOURCES.topics) == []
    real = regwatch.FeedItem("sebi", "STT on options revised", "", "", "", "k")
    assert regwatch.link_pages(real, SOURCES.topics) == ["capital-gains-and-stt"]


def test_watch_lands_once_a_day_and_reports_only_new_items(tmp_path: Path) -> None:
    landing = Landing(tmp_path / "landing")
    items = tmp_path / "items.jsonl"
    fetcher = FakeFetcher(
        {"https://example.test/sebi.xml": SEBI, "https://example.test/rbi.xml": RBI}
    )
    first = regwatch.watch(
        fetcher,
        SOURCES,
        today=date(2026, 10, 31),
        landing=landing,
        items_path=items,
        knowledge_time="2026-10-31T10:00:00+00:00",
    )
    assert first.status == {"sebi": "downloaded", "rbi_press": "downloaded"}
    assert len(first.new) == 3
    assert {tuple(i.pages) for i in first.new} == {("lot-size-and-tick",), (), ("rbi-policy-rate",)}
    again = regwatch.watch(
        fetcher,
        SOURCES,
        today=date(2026, 10, 31),
        landing=landing,
        items_path=items,
        knowledge_time="2026-10-31T11:00:00+00:00",
    )
    assert again.status == {"sebi": "skipped", "rbi_press": "skipped"} and again.new == []
    assert len(fetcher.calls) == 2  # the second run read the landed files
    rows = [json.loads(x) for x in items.read_text().splitlines()]
    assert all(r["event_time"] and r["knowledge_time"] for r in rows)


def test_a_failed_feed_is_reported_and_the_rest_still_run(tmp_path: Path) -> None:
    fetcher = FakeFetcher({"https://example.test/rbi.xml": RBI})
    out = regwatch.watch(
        fetcher,
        SOURCES,
        today=date(2026, 10, 31),
        landing=Landing(tmp_path),
        items_path=tmp_path / "i.jsonl",
        knowledge_time="t",
    )
    assert out.status["sebi"].startswith("failed") and out.status["rbi_press"] == "downloaded"


# --- gaps ----------------------------------------------------------------------------------------


def test_overdue_reads_recheck_dates_and_skips_struck_rows() -> None:
    text = (
        "| A-001 | old claim | f | e | 2026-01-01 |\n"
        "| A-002 | ~~struck~~ | f | e | 2026-01-01 |\n"
        "| A-003 | future | f | e | 2027-01-31, or later |\n"
        "| A-004 | no date | f | e | when the operator decides |\n"
    )
    late = gaps.overdue(text, date(2026, 10, 31))
    assert [o.id for o in late] == ["A-001"]


def test_stale_uncovered_and_asked() -> None:
    page = catalog.Page(
        "x", "market", "X", "one", "p", "What is normal (our data, as of 2026-06-01)"
    )
    assert gaps.stale_pages([page], date(2026, 10, 31), 90) == [page]
    assert gaps.stale_pages([page], date(2026, 7, 1), 90) == []
    found = gaps.uncovered(
        {"ok": True, "strip": {}, "newband": {}, "options": {}},
        {"strip": "index-returns", "options": "gone"},
        {"index-returns"},
    )
    assert found == ["newband: no page mapped", "options: mapped to gone, which has no page"]
    rows = [
        {"query": "Gamma Flip", "knowledge_time": "2026-10-30"},
        {"query": "gamma flip", "knowledge_time": "2026-10-31"},
        {"query": "old", "knowledge_time": "2026-01-01"},
    ]
    assert gaps.asked_without_page(rows, "2026-10-25") == [("gamma flip", 2)]


# --- the agent -----------------------------------------------------------------------------------


def _agent() -> dict[str, Any]:
    raw = yaml.safe_load(Path("config/agents/knowledge_keeper.yaml").read_text())
    raw["uses_model"] = False
    raw["daily_requests"] = 0
    return {"knowledge_keeper": effective(AgentSpec(**raw), None)}


def test_the_first_daily_run_records_without_flooding_then_reports_new_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(regwatch, "ITEMS", tmp_path / "items.jsonl")
    monkeypatch.setattr(regwatch, "LANDING", tmp_path / "landing")
    monkeypatch.setattr(regwatch, "load_sources", lambda: SOURCES)
    monkeypatch.setattr(
        normals, "compute", lambda now=None: {"knowledge_time": "t", "metrics": {}, "left_out": []}
    )
    monkeypatch.setattr(normals, "save", lambda payload, path=None: tmp_path / "n.json")
    feeds = {"https://example.test/sebi.xml": SEBI, "https://example.test/rbi.xml": RBI}
    monkeypatch.setattr(knowledge_keeper, "_fetcher", lambda: FakeFetcher(feeds))
    now = datetime(2026, 10, 31, 11, 0, tzinfo=UTC)
    first = runtime.run("knowledge_keeper", root=tmp_path, agents=_agent(), now=now)
    assert first.status == "ok"
    assert [i.kind for i in first.items] == ["finding"] and "3 existing items" in first.items[
        0
    ].title

    newer = SEBI.replace(
        b"</channel>",
        b"<item><title>Change in STT on options</title><description>d</description><link>https://www.sebi.gov.in/n_3.html</link><pubDate>1 Nov, 2026 +0530</pubDate></item></channel>",
    )
    feeds["https://example.test/sebi.xml"] = newer
    second = runtime.run(
        "knowledge_keeper",
        root=tmp_path,
        agents=_agent(),
        now=datetime(2026, 11, 1, 11, 0, tzinfo=UTC),
    )
    leads = [i for i in second.items if i.kind == "lead"]
    assert len(leads) == 1 and leads[0].data["pages"] == ["capital-gains-and-stt"]
    assert leads[0].ref == "https://www.sebi.gov.in/n_3.html"


def test_accept_writes_only_into_the_metrics_library(tmp_path: Path) -> None:
    (tmp_path / "docs/METRICS/market").mkdir(parents=True)
    page = tmp_path / "docs/METRICS/market/x.md"
    page.write_text("# old\n")
    draft = tmp_path / "draft-x.md"
    draft.write_text("# new\n")
    draft.with_suffix(".json").write_text(json.dumps({"page": "docs/METRICS/market/x.md"}))
    assert knowledge_keeper.accept(draft, root=tmp_path) == page and page.read_text() == "# new\n"
    draft.with_suffix(".json").write_text(json.dumps({"page": "mandate.yaml"}))
    with pytest.raises(ValueError):
        knowledge_keeper.accept(draft, root=tmp_path)
    draft.with_suffix(".json").write_text(json.dumps({"page": "docs/METRICS/../../mandate.md"}))
    with pytest.raises(ValueError):
        knowledge_keeper.accept(draft, root=tmp_path)


def test_only_titles_are_matched_and_routine_notices_are_skipped() -> None:
    topics = [regwatch.Topic(keywords=["lot size"], pages=["lot-size-and-tick"])]
    in_summary = regwatch.FeedItem("nse", "Circular", "", "", "revises the lot size", "k")
    assert regwatch.link_pages(in_summary, topics) == []
    routine = regwatch.FeedItem("nse", "DIVIDEND: lot size adjusted for INFY", "", "", "", "k")
    assert regwatch.link_pages(routine, topics, ["DIVIDEND:"]) == []
    rule = regwatch.FeedItem("nse", "Revision in lot size of index derivatives", "", "", "", "k")
    assert regwatch.link_pages(rule, topics, ["DIVIDEND:"]) == ["lot-size-and-tick"]


def test_weekly_drafts_from_new_notices_and_drops_invented_figures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = tmp_path / "items.jsonl"
    monkeypatch.setattr(regwatch, "ITEMS", items)
    monkeypatch.setattr(regwatch, "LANDING", tmp_path / "landing")
    topics = regwatch.Sources(
        feeds=[],
        topics=[
            regwatch.Topic(keywords=["lot size"], pages=["lot-size-and-tick", "sebi-fno-rules"])
        ],
    )
    monkeypatch.setattr(regwatch, "load_sources", lambda: topics)
    monkeypatch.setattr(
        normals, "compute", lambda now=None: {"knowledge_time": "t", "metrics": {}, "left_out": []}
    )
    monkeypatch.setattr(normals, "save", lambda payload, path=None: tmp_path / "n.json")
    monkeypatch.setattr(knowledge_keeper, "_market_context", dict)
    monkeypatch.setattr(gaps, "ASSUMPTIONS", tmp_path / "none.md")
    now = datetime(2026, 11, 1, 11, 0, tzinfo=UTC)
    regwatch.record(
        [
            regwatch.FeedItem(
                "nse_circulars",
                "Revision in lot size of index derivatives",
                "https://x/1",
                "2026-10-31",
                "Nifty lot size becomes 65 from 1 Jan 2027",
                "k1",
            )
        ],
        "2026-10-31T12:00:00+00:00",
        items,
    )
    page = catalog.find("lot-size-and-tick")[0]
    other = catalog.find("sebi-fno-rules")[0]
    answers = iter(
        [
            page.text.replace(
                "**Traps:**", "Nifty lot size 65 from 1 Jan 2027 (NSE, 2026-10-31).\n\n**Traps:**"
            ),
            other.text + "\nInvented 7,777 contracts.",
        ]
    )

    raw = yaml.safe_load(Path("config/agents/knowledge_keeper.yaml").read_text())
    agents = {"knowledge_keeper": effective(AgentSpec(**raw), None)}
    out = runtime.run(
        "knowledge_keeper",
        args={"mode": "weekly"},
        root=tmp_path,
        agents=agents,
        asker=lambda system, user, accept: next(answers),
        now=now,
    )
    drafts = [i for i in out.items if i.kind == "draft"]
    assert len(drafts) == 1 and drafts[0].needs_approval
    assert "make metrics-accept DRAFT=" in drafts[0].body
    assert "65" in Path(drafts[0].ref).read_text()
    assert any("sebi-fno-rules dropped" in n and "7,777" in n for n in out.notes)


def test_option_normals_count_each_session_once(tmp_path: Path) -> None:
    cache = tmp_path / "options.jsonl"
    rows = [
        {"day": "2026-10-01", "point": {"day": "2026-10-01", "pcr_oi": 0.8, "atm_iv": 0.1}},
        {"day": "2026-10-01", "point": {"day": "2026-10-01", "pcr_oi": 0.9, "atm_iv": 0.11}},
        {"day": "2026-10-02", "point": None},
        {"day": "2026-10-03", "point": {"day": "2026-10-03", "pcr_oi": 1.2, "atm_iv": 0.13}},
    ]
    cache.write_text("\n".join(json.dumps(r) for r in rows))
    assert normals._options(cache) == ([0.9, 1.2], [0.11, 0.13])
