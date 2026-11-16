"""The evolutionary search (ADR-177): islands, lineages, penalties, the bandit, replay."""

from __future__ import annotations

import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from eulerlab.db.stream import read_rows
from eulerlab.research import evolve, lang, novelty

DAYS = [date(2022, 1, 3) + timedelta(days=i) for i in range(400)]


def _spec(kind: str = "intraday", when: str = "ge(abs(gap), 0.03)", **more: Any) -> lang.Spec:
    body = {"shape": "event", "kind": kind, "when": when, "score": "abs(gap)", **more}
    if kind == "swing":
        body.setdefault("hold", 5)
    return lang.Spec(**body)


class World:
    """A made-up market: every rule has its own return stream, drawn from its fingerprint."""

    def __init__(self, sharpe: float = 2.0, same: bool = False) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.sharpe, self.same = sharpe, same

    def __call__(self, spec: lang.Spec, island: str, parents: Any) -> dict[str, Any]:
        self.calls.append((island, tuple(parents)))
        rng = random.Random("same" if self.same else spec.fingerprint())
        daily = {d: rng.gauss(0.001, 0.01) for d in DAYS}
        size = spec.complexity["size"]
        return {
            "id": f"x{len(self.calls):04d}",
            "clean": True,
            "net": {"sharpe": self.sharpe - 0.01 * size},
            "daily": daily,
        }


SEEDS = [
    _spec(),
    _spec("swing"),
    _spec(when="ge(delay(delivery_ratio, 1), 2)"),
    _spec("swing", when="has(delay(bulk_buy, 1))"),
    _spec(when="lt(delay(fii_net, 1), 0)"),
]


def _night(tmp_path: Path, world: World, **more: Any) -> evolve.Night:
    return evolve.run(
        budget=40, seeds=SEEDS, evaluate=world, peers={}, day=date(2026, 11, 13),
        path=tmp_path / "evolve.jsonl", **more,
    )  # fmt: skip


def test_a_rule_lives_on_the_island_of_its_kind_and_its_data() -> None:
    assert evolve.island_of(_spec()) == "intraday:price"
    assert evolve.island_of(_spec("swing", when="has(delay(bulk_buy, 1))")) == "swing:events"
    assert (
        evolve.island_of(_spec(when="and(gt(gap, 0), lt(delay(fii_net, 1), 0))"))
        == "intraday:flows"
    )


def test_every_mutation_is_a_valid_rule_with_no_look_ahead() -> None:
    rng = random.Random(1)
    parent, other = (
        _spec("swing", when="and(ge(abs(gap), 0.03), ge(delay(ret(5), 1), 0.1))"),
        SEEDS[1],
    )
    made = [evolve.mutate(parent, rng, other) for _ in range(300)]
    children = [c for c in made if c is not None]
    assert len(children) > 100
    assert len({c.fingerprint() for c in children}) > 10
    for child in children:
        assert child.kind == "swing" and child.side == "long"
        lang.Spec.model_validate(child.model_dump(mode="json"))  # compiles: no look-ahead


def test_no_move_only_changes_a_number_window_or_hold() -> None:
    rng = random.Random(3)
    parent = _spec("swing", when="and(ge(abs(gap), 0.03), ge(delay(ret(5), 1), 0.1))")
    for _ in range(300):
        child = evolve.mutate(parent, rng)
        if child is not None:
            assert novelty.rule_key(child) != novelty.rule_key(parent), child.describe()


def test_a_night_keeps_half_its_budget_on_each_side_and_tracks_lineages(tmp_path: Path) -> None:
    world = World()
    night = _night(tmp_path, world)
    sides = Counter(island.split(":")[0] for island, _ in world.calls)
    assert night.tried == len(world.calls) > 20
    assert abs(sides["intraday"] - sides["swing"]) <= 12
    bred = [m for m in night.admitted if m.parents]
    assert bred, "children of pool members were admitted"
    pool = evolve.load(tmp_path / "evolve.jsonl")
    for member in bred:
        assert member.generation >= 1 and member.root in {m.root for m in pool.members.values()}
    assert sum(pool.children.values()) == night.tried


def test_the_same_day_replays_the_same_night(tmp_path: Path) -> None:
    a = _night(tmp_path / "a", World())
    b = _night(tmp_path / "b", World())
    assert [m.spec.fingerprint() for m in a.admitted] == [m.spec.fingerprint() for m in b.admitted]


def test_a_second_night_does_not_try_a_rule_twice(tmp_path: Path) -> None:
    world = World()
    _night(tmp_path, world)
    first = len(world.calls)
    _night(tmp_path, world)
    rows = [r for r in read_rows(tmp_path / "evolve.jsonl", evolve.KIND) if r["event"] == "try"]
    assert len(rows) == len(world.calls) > first
    assert len({r["fingerprint"] for r in rows}) == len(rows)


def test_a_rule_that_moves_with_a_passed_strategy_is_refused(tmp_path: Path) -> None:
    world = World(same=True)
    rng = random.Random("same")
    peer = {d: rng.gauss(0.001, 0.01) for d in DAYS}
    night = evolve.run(
        budget=10, seeds=SEEDS, evaluate=world, peers={"H-0161": peer}, day=date(2026, 11, 13),
        path=tmp_path / "e.jsonl",
    )  # fmt: skip
    assert night.tried and not night.admitted
    assert any("moves with H-0161" in why for why in night.refused)


def test_pool_members_must_differ_from_each_other(tmp_path: Path) -> None:
    night = evolve.run(
        budget=10, seeds=SEEDS, evaluate=World(same=True), peers={}, day=date(2026, 11, 13),
        path=tmp_path / "e.jsonl",
    )  # fmt: skip
    assert len(night.admitted) == 1
    assert any("moves with pool member" in why for why in night.refused)


def test_size_and_likeness_are_charged() -> None:
    pool = evolve.Pool()
    small, big = (
        _spec(),
        _spec(when="and(ge(abs(gap), 0.03), and(ge(delay(ret(5), 1), 0.1), gt(gap, 0)))"),
    )
    found = {"clean": True, "net": {"sharpe": 1.0}, "daily": {}}
    a, _ = evolve.judge(small, found, pool, {})
    b, _ = evolve.judge(big, found, pool, {})
    assert a is not None and b is not None and a > b
    pool.members["m"] = evolve.Member("m", small, "intraday:price", 1.0, 1.0, "m", 0)
    c, _ = evolve.judge(small, found, pool, {})
    assert c is not None and c == pytest.approx(a - evolve.LIKENESS_CHARGE)
    assert evolve.judge(small, {"clean": False}, pool, {})[0] is None


def test_neglected_lineages_get_more_children() -> None:
    members = [
        evolve.Member(f"m{i}", _spec(), "intraday:price", 1.0, 1.0, root, 0)
        for i, root in enumerate(["busy", "quiet"])
    ]
    rng = random.Random(3)
    picks = Counter(
        evolve.choose_parent(members, {"busy": 400, "quiet": 0}, rng).root for _ in range(2000)
    )
    assert (
        picks["quiet"] > picks["busy"] * 0.6
    )  # m1 ranks no better, yet is picked far more than its rank


def test_an_island_with_many_tries_and_nothing_admitted_is_closed() -> None:
    pool = evolve.Pool(tried={"intraday:flows": evolve.SATURATED}, admitted={})
    picked = evolve.allot(200, pool, random.Random(0), {})
    assert "intraday:flows" not in picked and len(picked) == 200


def test_the_bandit_leans_to_islands_that_yield() -> None:
    pool = evolve.Pool(
        tried={"swing:price": 50, "swing:volume": 50},
        admitted={"swing:price": 30, "swing:volume": 0},
    )
    picked = Counter(evolve.allot(400, pool, random.Random(0), {}))
    assert picked["swing:price"] > 3 * picked["swing:volume"]


def test_the_model_proposes_and_code_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = _spec(when="ge(abs(gap), 0.05)").model_dump(mode="json")
    bad = {**good, "when": "ge(ret(5), 0.1)"}  # reads a close on the entry day
    answer = '{"cards": [{"spec": %s, "why": "a"}, {"spec": %s, "why": "b"}]}'
    import json

    asked: list[str] = []

    def ask(system: str, user: str) -> str:
        asked.append(user)
        return answer % (json.dumps(good), json.dumps(bad))

    assert [s.when for s in evolve.proposals(ask("", ""))] == ["ge(abs(gap), 0.05)"]
    monkeypatch.setattr(evolve, "MODEL_SHARE", 1.0)
    tried = novelty.Seen()
    tried.add(novelty.rule_key(SEEDS[0]), "H-0900")
    night = _night(tmp_path, World(), ask=ask, ideas=tried)
    assert night.from_model >= 1
    assert night.refused.get("a tried idea with other numbers", 0) >= 1  # gap at 5%, not 3%
    assert "never see prices" in evolve.SYSTEM and "net Sharpe" in asked[-1]


def test_survivors_are_the_best_of_each_island_that_held(tmp_path: Path) -> None:
    night = _night(tmp_path, World())
    best = evolve.survivors(night, lambda m: True)
    assert len(best) == len({m.island for m in night.admitted})
    assert evolve.survivors(night, lambda m: False) == []
    text = evolve.card_yaml("H-0999", best[0], day=date(2026, 11, 13), tried=night.tried)
    assert "engine_v2:" in text and "evolved_rules" in text
