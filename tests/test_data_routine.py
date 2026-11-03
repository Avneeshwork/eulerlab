"""The data agent's routine, merge-back, the token log and the watchdog (ADR-132)."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from eulerlab.agents import jobs, runtime, tasks
from eulerlab.agents.runtime import WorkerResult
from eulerlab.agents.spec import all_effective
from eulerlab.agents.workers import data as data_worker
from eulerlab.agents.workers import manager, watchdog
from eulerlab.ingest import merge_back
from eulerlab.llm import usage

NOW = datetime(2026, 11, 4, 6, 30, tzinfo=UTC)  # 12:00 IST, a Wednesday


def _gz(rows: list[dict[str, Any]]) -> bytes:
    return gzip.compress(("\n".join(json.dumps(r) for r in rows) + "\n").encode(), mtime=0)


def _rows(payload: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in gzip.decompress(payload).decode().splitlines() if line]


@dataclass
class Bucket:
    objects: dict[str, bytes] = field(default_factory=dict)
    puts: list[str] = field(default_factory=list)
    hide: set[str] = field(default_factory=set)
    """Keys a listing does not show yet (an upload that has not settled)."""

    def list_sizes(self, prefix: str) -> dict[str, int]:
        return {
            k: len(v)
            for k, v in self.objects.items()
            if k.startswith(prefix) and k not in self.hide
        }

    def head_sha256(self, key: str) -> str | None:
        return None

    def put(self, key: str, payload: bytes, sha256: str) -> None:
        self.objects[key] = payload
        self.puts.append(key)

    def get(self, key: str) -> bytes:
        return self.objects[key]


BAR = {"symbol": "X", "event_time": "2026-03-01T00:00:00+00:00", "close": 1.0}


# --- merge -----------------------------------------------------------------


def test_a_row_is_the_same_row_whatever_time_we_held_it() -> None:
    a = {**BAR, "knowledge_time": "2026-03-01T00:01:00+00:00", "receipt_time": "x"}
    b = {**BAR, "knowledge_time": "2026-11-02T00:00:00+00:00", "receipt_time": "y"}
    assert merge_back.identity(a) == merge_back.identity(b)
    merged = merge_back.merge([("b", b)], [("a", a)])
    assert merged.lines == ["a"] and merged.earlier == 1 and merged.added == 0


def test_rows_only_the_local_copy_has_are_added_after_the_buckets() -> None:
    old = {**BAR, "knowledge_time": "2026-03-01T00:01:00+00:00"}
    new = {**BAR, "close": 2.0, "knowledge_time": "2026-03-01T00:02:00+00:00"}
    merged = merge_back.merge([("old", old), ("old", old)], [("old", old), ("new", new)])
    assert merged.lines == ["old", "new"]
    assert (merged.added, merged.earlier, merged.repeats) == (1, 0, 1)


def test_a_local_duplicate_is_deleted_and_the_bucket_left_alone(tmp_path: Path) -> None:
    row = {**BAR, "knowledge_time": "2026-03-01T00:01:00+00:00"}
    bucket = Bucket({"p/crypto/X/m.jsonl.gz": _gz([row, {**row, "close": 2.0}])})
    local = tmp_path / "crypto" / "X" / "m.jsonl.gz"
    local.parent.mkdir(parents=True)
    local.write_bytes(_gz([{**row, "receipt_time": "later"}]))
    report = merge_back.merge_tree(tmp_path, "crypto", bucket, prefix="p/")
    assert report.duplicates_deleted == 1 and not local.exists() and bucket.puts == []


def test_new_rows_are_merged_into_the_bucket_before_the_local_file_goes(tmp_path: Path) -> None:
    kept = {"guid": "a", "title": "old", "knowledge_time": "2026-10-01T00:00:00+00:00"}
    fresh = {"guid": "b", "title": "new", "knowledge_time": "2026-10-30T00:00:00+00:00"}
    key = "p/news/crypto/2026-10.jsonl.gz"
    bucket = Bucket({key: _gz([kept] * 1 + [{**kept, "guid": f"z{i}"} for i in range(30)])})
    local = tmp_path / "news" / "crypto" / "2026-10.jsonl.gz"
    local.parent.mkdir(parents=True)
    local.write_bytes(_gz([fresh]))
    report = merge_back.merge_tree(tmp_path, "news", bucket, prefix="p/")
    assert report.merged_uploaded == 1 and report.rows_added == 1 and not local.exists()
    guids = [r["guid"] for r in _rows(bucket.objects[key])]
    assert guids[0] == "a" and guids[-1] == "b" and len(guids) == 32


def test_a_merged_file_the_bucket_does_not_show_yet_is_kept(tmp_path: Path) -> None:
    key = "p/news/fx/2026-10.jsonl.gz"
    bucket = Bucket({key: _gz([{"guid": "a"}] * 3)}, hide=set())
    local = tmp_path / "news" / "fx" / "2026-10.jsonl.gz"
    local.parent.mkdir(parents=True)
    local.write_bytes(_gz([{"guid": "b"}]))

    @dataclass
    class Slow(Bucket):
        def put(self, key: str, payload: bytes, sha256: str) -> None:
            self.objects[key] = payload
            self.hide.add(key)

    bucket = Slow(bucket.objects)
    report = merge_back.merge_tree(tmp_path, "news", bucket, prefix="p/")
    assert local.exists() and report.merged_uploaded == 0 and len(report.unresolved) == 1


def test_a_file_that_is_not_json_lines_is_reported_and_kept(tmp_path: Path) -> None:
    bucket = Bucket({"p/us/a.parquet": b"xxxx"})
    local = tmp_path / "us" / "a.parquet"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"yy")
    report = merge_back.merge_tree(tmp_path, "us", bucket, prefix="p/")
    assert local.exists() and report.unresolved and "not JSON lines" in report.unresolved[0]


def test_the_limit_leaves_the_rest_for_the_next_run(tmp_path: Path) -> None:
    bucket = Bucket()
    for i in range(3):
        key = f"p/us/actions/{i}.jsonl.gz"
        bucket.objects[key] = _gz([{"id": i}, {"id": i + 100}])
        path = tmp_path / "us" / "actions" / f"{i}.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_gz([{"id": i}]))
    reports = merge_back.run(
        bucket, prefix="p/", trees=["us"], root=tmp_path, limit=2, log=lambda _: None
    )
    assert reports[0].checked == 2 and reports[0].left_for_next_run == 1


def test_a_dry_run_changes_nothing(tmp_path: Path) -> None:
    key = "p/news/x/m.jsonl.gz"
    bucket = Bucket({key: _gz([{"g": 1}] * 4)})
    local = tmp_path / "news" / "x" / "m.jsonl.gz"
    local.parent.mkdir(parents=True)
    local.write_bytes(_gz([{"g": 2}]))
    report = merge_back.merge_tree(tmp_path, "news", bucket, prefix="p/", dry_run=True)
    assert report.merged_uploaded == 1 and local.exists() and bucket.puts == []


# --- the data agent ----------------------------------------------------------


def test_todays_missing_data_is_due_tonight_until_21_ist() -> None:
    row = SimpleNamespace(status="missing", detail="today's data not in yet")
    assert data_worker.due_tonight(row, datetime(2026, 11, 4, 10, 45, tzinfo=UTC))  # 16:15 IST
    assert not data_worker.due_tonight(row, datetime(2026, 11, 4, 16, 0, tzinfo=UTC))  # 21:30
    assert not data_worker.due_tonight(
        SimpleNamespace(status="missing", detail="nothing held"), NOW
    )


def _ctx(tmp_path: Path, answer: str = "", **options: Any) -> Any:
    notes: list[str] = []
    asked: list[str] = []

    def ask(system: str, user: str, accept: Any = None) -> str:
        asked.append(user)
        return answer

    return SimpleNamespace(
        options=options,
        notes=notes,
        step=lambda *_a, **_k: None,
        can_ask=lambda: bool(answer),
        ask=ask,
        asked=asked,
        name="data",
        root=tmp_path,
        now=NOW,
    )


def test_upkeep_uploads_then_merges_and_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EULERLAB_NO_CLOUD", raising=False)
    monkeypatch.chdir(tmp_path)
    bucket = Bucket({"p/news/x/m.jsonl.gz": _gz([{"g": 1}] * 4)})
    local = tmp_path / "data" / "landing" / "news" / "x" / "m.jsonl.gz"
    local.parent.mkdir(parents=True)
    local.write_bytes(_gz([{"g": 2}]))
    monkeypatch.setattr(data_worker, "_cloud", lambda: (bucket, SimpleNamespace(prefix="p/")))
    mirrored: list[Any] = []

    def mirror(names: Any, store: Any, config: Any, landing: Any, root: Any, **kw: Any) -> int:
        mirrored.append((list(names), kw))
        print("news: uploaded 3, already there 1")
        print("news: deleted 2 local files (0.1 MB), kept 1 not confirmed in the bucket")
        return 0

    monkeypatch.setattr("eulerlab.ingest.sync_cloud.mirror_trees", mirror)
    items, summary = data_worker._upkeep(_ctx(tmp_path, upkeep_trees=["news"]))
    assert mirrored == [(["news"], {"then_delete": True})]
    assert summary["uploaded"] == 3 and summary["merged"] == 1 and summary["rows_added"] == 1
    assert not local.exists() and items == []
    assert json.loads((tmp_path / merge_back.REPORT).read_text())["trees"][0]["tree"] == "news"


def test_upkeep_waits_while_the_feed_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.ingest import filelock

    monkeypatch.delenv("EULERLAB_NO_CLOUD", raising=False)
    with filelock.exclusive("feed", wait=False, what="make daily"):
        items, summary = data_worker._upkeep(_ctx(tmp_path))
    assert items == [] and "feed is running" in summary["line"]


def test_upkeep_is_skipped_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EULERLAB_NO_CLOUD", "1")
    assert data_worker._upkeep(_ctx(tmp_path))[1]["line"].startswith("Upkeep skipped")


def _problem() -> runtime.Item:
    return runtime.Item(kind="alert", title="feed: FX failed", body="TimeoutError", severity="warn")


def test_ai_help_reruns_one_allowed_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[list[str]] = []

    def rerun(steps: list[str]) -> jobs.Rerun:
        ran.append(list(steps))
        return jobs.Rerun(tuple(steps), True, "ok")

    monkeypatch.setattr(jobs, "rerun", rerun)
    answer = json.dumps(
        {"cause": "a timeout", "fix": "run it again", "action": "rerun", "step": "FX"}
    )
    items = data_worker._ask_for_help(_ctx(tmp_path, answer), [_problem()], already=[])
    assert ran == [["FX"]] and items[1].title.startswith("re-ran FX")


def test_ai_help_never_runs_a_step_outside_the_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "rerun", lambda steps: pytest.fail("must not run"))
    answer = json.dumps({"cause": "c", "fix": "f", "action": "rerun", "step": "rm -rf data"})
    items = data_worker._ask_for_help(_ctx(tmp_path, answer), [_problem()], already=[])
    assert len(items) == 1


def test_ai_help_gives_a_code_problem_to_the_head(tmp_path: Path) -> None:
    answer = json.dumps(
        {"cause": "the column was renamed", "fix": "update the parser", "action": "head"}
    )
    items = data_worker._ask_for_help(_ctx(tmp_path, answer), [_problem()], already=[])
    [task] = tasks.load(tmp_path).values()
    assert task.owner == "head_platform" and "renamed" in task.detail
    assert task.id in items[-1].title


@pytest.fixture
def no_reruns(monkeypatch: pytest.MonkeyPatch) -> None:
    """The watchdog must not re-run real agents in a test: one reached B2."""
    monkeypatch.setattr(watchdog, "remedy", lambda ctx, problems: ([], []))


def test_an_answer_that_is_not_json_is_noted_not_fatal(tmp_path: Path, no_reruns: None) -> None:
    ctx = _ctx(tmp_path, "I think the feed is late.")
    assert data_worker._ask_for_help(ctx, [_problem()], already=[]) == []
    assert ctx.notes == ["AI help failed (ValueError)"]
    _run(tmp_path, "lab", NOW - timedelta(minutes=8), "failed", "boom")
    out = runtime.run("watchdog", root=tmp_path, now=NOW, asker=lambda *a: "no json here")
    assert out.status == "ok" and "AI help failed (ValueError)" in out.notes


def test_ai_help_marks_what_only_the_operator_can_fix(tmp_path: Path) -> None:
    answer = json.dumps({"cause": "the API key expired", "fix": "renew it", "action": "operator"})
    items = data_worker._ask_for_help(_ctx(tmp_path, answer), [_problem()], already=[])
    assert items[0].needs_approval and items[0].kind == "alert"


def test_the_committed_data_agent_runs_the_routine() -> None:
    from eulerlab.agents.spec import all_effective

    spec = all_effective()["data"].spec
    assert spec.uses_model and spec.provider == "groq"
    assert all(spec.options.get(k) for k in ("auto_rerun", "upkeep", "ai_help"))


def test_the_data_watch_job_runs_every_two_hours_from_six_to_eight() -> None:
    from tools import schedule_daily

    job = schedule_daily.JOBS["data-watch"]
    text = schedule_daily.plist(Path("/repo"), hour=job.hour, minute=job.minute, job=job)
    hours = [int(x.split("</integer>")[0]) for x in text.split("<key>Hour</key><integer>")[1:]]
    assert hours == [6, 8, 10, 12, 14, 16, 18, 20] and "make agent NAME=data" in text


# --- the token log -----------------------------------------------------------


def test_tokens_are_logged_by_the_agent_and_run_that_asked() -> None:
    with usage.asking("research", "run-1"):
        usage.record("groq", "gpt-oss", {"prompt_tokens": 900, "completion_tokens": 100})
    usage.record("claude", "opus", {"input_tokens": 5, "output_tokens": 7})
    assert usage.run_tokens("research", "run-1") == 1000
    assert [r["agent"] for r in usage.rows()] == ["research", "assistant"]
    assert usage.rows()[1]["total"] == 12


def test_a_worker_that_exits_fails_its_run_not_the_process(tmp_path: Path) -> None:
    def worker(ctx: Any) -> WorkerResult:
        raise SystemExit("B2_KEY_ID is not set.")

    out = runtime.run("operations", root=tmp_path, now=NOW, worker=worker)
    assert out.status == "failed" and "B2_KEY_ID" in out.summary


def test_a_run_records_its_tokens(tmp_path: Path) -> None:
    def worker(ctx: Any) -> WorkerResult:
        ctx.requests = 1
        usage.record("groq", "m", {"prompt_tokens": 40, "completion_tokens": 2})
        return WorkerResult("done")

    out = runtime.run("operations", root=tmp_path, now=NOW, worker=worker)
    assert out.tokens == 42


# --- the watchdog ------------------------------------------------------------


def _run(
    root: Path,
    name: str,
    at: datetime,
    status: str = "ok",
    summary: str = "fine",
    requests: int = 0,
) -> None:
    def worker(ctx: Any) -> WorkerResult:
        ctx.requests = requests
        return WorkerResult(summary, status=status)  # type: ignore[arg-type]

    runtime.run(name, root=root, now=at, worker=worker)


OPTIONS = {"expect": {"operations": 26}, "weekdays_only": [], "window_hours": 26}


def test_three_failures_in_a_row_are_stuck(tmp_path: Path) -> None:
    for minutes in (1, 2, 3):
        _run(tmp_path, "portfolio", NOW - timedelta(minutes=minutes), "failed", "KeyError: 'x'")
    agents = all_effective(tmp_path)
    problems, _ = watchdog.check_runs(agents, now=NOW, root=tmp_path, options={})
    kinds = sorted({p.kind for p in problems if p.agent == "portfolio"})
    assert kinds == ["failed", "stuck"]
    assert any("the same way" in p.title for p in problems)


def test_a_missed_run_is_found_and_weekends_are_allowed(tmp_path: Path) -> None:
    _run(tmp_path, "operations", NOW - timedelta(hours=30))
    agents = all_effective(tmp_path)
    problems, _ = watchdog.check_runs(agents, now=NOW, root=tmp_path, options=OPTIONS)
    assert [p.kind for p in problems if p.agent == "operations"] == ["missed"]
    saturday = datetime(2026, 11, 7, 6, 0, tzinfo=UTC)
    _run(tmp_path, "operations", saturday - timedelta(hours=40))
    weekend = {**OPTIONS, "weekdays_only": ["operations"]}
    problems, _ = watchdog.check_runs(agents, now=saturday, root=tmp_path, options=weekend)
    assert not [p for p in problems if p.agent == "operations"]


def test_tokens_and_requests_over_budget_are_flagged(tmp_path: Path) -> None:
    _run(tmp_path, "operations", NOW - timedelta(minutes=5), requests=2)
    with usage.asking("research", "r"):
        for _ in range(3):
            usage.record(
                "groq", "m", {"prompt_tokens": 25_000, "completion_tokens": 1_000}, now=NOW
            )
    agents = all_effective(tmp_path)
    _, seen = watchdog.check_runs(agents, now=NOW, root=tmp_path, options={})
    problems, spend = watchdog.check_model_use(
        agents, seen, now=NOW + timedelta(minutes=1), options={}
    )
    titles = " | ".join(p.title for p in problems)
    assert "operations asked a model but is defined without one" in titles
    assert "research used 78,000 tokens in a day" in titles
    assert "research sends 26,000 tokens a request" in titles
    assert spend["tokens_by_agent"]["research"] == 78_000


def test_blocked_and_returned_tasks_are_flagged(tmp_path: Path) -> None:
    t = tasks.create(
        title="Grade bulk deals",
        owner="data",
        department="platform",
        created_by="ceo",
        kind="check_dataset",
        root=tmp_path,
        now=NOW,
    )
    tasks.record(t.id, "blocked", "head_platform", {"note": "refused"}, root=tmp_path, now=NOW)
    problems = watchdog.check_tasks(tmp_path, now=NOW)
    assert problems and problems[0].title.startswith("task blocked")


def test_the_watchdog_reruns_a_cheap_agent_once_a_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[str] = []
    real = runtime.run

    def fake(name: str, **kw: Any) -> runtime.Output:
        if name == "watchdog":
            return real(name, **kw)
        ran.append(name)
        return real(name, root=tmp_path, now=NOW, worker=lambda ctx: WorkerResult("ok again"))

    _run(tmp_path, "portfolio", NOW - timedelta(minutes=9), "failed", "boom")
    _run(tmp_path, "lab", NOW - timedelta(minutes=8), "failed", "boom")
    monkeypatch.setattr(runtime, "run", fake)
    first = fake("watchdog", root=tmp_path, now=NOW, asker=lambda *a: "{}")
    assert "portfolio" in ran and "lab" not in ran  # never the lab: it spends trials
    assert "portfolio" in first.summary
    once = list(ran)
    fake("watchdog", root=tmp_path, now=NOW + timedelta(minutes=30), asker=lambda *a: "{}")
    assert ran == once


def test_ai_help_turns_a_problem_into_a_task_for_the_head(tmp_path: Path, no_reruns: None) -> None:
    _run(tmp_path, "lab", NOW - timedelta(minutes=8), "failed", "ValueError: bad card")
    answer = json.dumps(
        {
            "problems": [
                {
                    "agent": "lab",
                    "cause": "a malformed card",
                    "fix": "fix the card check",
                    "who": "head",
                }
            ]
        }
    )
    out = runtime.run("watchdog", root=tmp_path, now=NOW, asker=lambda *a: answer)
    [task] = [t for t in tasks.load(tmp_path).values() if t.created_by == "watchdog"]
    assert task.owner == "head_research" and "malformed card" in task.detail
    assert out.requests == 1


# --- the head's checklist and the research card ------------------------------


def test_a_research_task_that_drafted_nothing_goes_back(tmp_path: Path) -> None:
    t = tasks.create(
        title="Find papers",
        owner="research",
        department="research",
        created_by="head_research",
        kind="research_topic",
        root=tmp_path,
        now=NOW,
    )
    tasks.record(t.id, "started", "work", root=tmp_path, now=NOW)
    tasks.record(
        t.id,
        "finished",
        "research",
        {"run_id": "r", "run_status": "ok", "summary": "momentum: 0 drafted, 0 repeats"},
        root=tmp_path,
        now=NOW,
    )
    checked = manager.check(tasks.load(tmp_path)[t.id], "head_research", tmp_path, NOW)
    assert checked.status == "assigned" and checked.returns == 1
    assert "delivered what the task asked for" in str(checked.history[-1])
    assert manager.DELIVERS["research_topic"].search("x: 5 read, 3 drafted (0 complete), 2 not")


def test_a_card_whose_formula_does_not_parse_is_incomplete() -> None:
    from datetime import date

    from eulerlab.research import card, paper_agent

    good = card.Card(
        id="PENDING",
        title="t",
        claim="c",
        rationale="r",
        configurations=[{"feature": "formula:neg(ret(1))", "holding_days": 20}],
        red_flags=["a", "b", "c"],
        holdout_starts=date(2025, 1, 1),
        source_url="https://x",
        source_fetched="2026-11-03",
    )
    bad = card.Card(**{**good.__dict__, "configurations": [{"feature": "formula:neg(ret(0))"}]})
    assert not [p for p in paper_agent.card_problems(good) if "formula" in p]
    assert any("formula does not parse" in p for p in paper_agent.card_problems(bad))
