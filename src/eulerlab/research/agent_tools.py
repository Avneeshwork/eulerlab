"""The research loop's tools: what an agent may look up, measure and test while it thinks.

Issue #162 (ADR-190) gave the autopilot four tools; #163 and #164 (ADR-191) add
the rest of a researcher's bench: measure a signal before making a rule of it,
define new signals, test an event, and keep a notebook across nights. Every
tool is called through the assistant's tool loop (`assistant.chat.ask`), under
the same host, retention and redaction locks, each request kept in full
(`llm/trace.py`).

| Tool | Reads | Writes |
|---|---|---|
| `language` | language v2's fields and operators, and the features agents defined | nothing |
| `signals` | the old rule engine's vocabulary and spec shape | nothing |
| `claim_record` | the knowledge base (ADR-180), as the assistant's tool | nothing |
| `family_record` | the experiment store: per family, rules tried, passes, clean | nothing |
| `agenda` / `ask_question` / `record_finding` | the research agenda (`research/agenda.py`) | agenda events |
| `define_feature` | the panel, to `discovery_end` | one feature-registry line, kept or refused |
| `feature_ic` | the panel, to `discovery_end` | one experiment-store row |
| `event_study` | the panel, to `discovery_end` | one experiment-store row |
| `screen_rule` / `screen_formula` | the panel, to `discovery_end` | one experiment-store row |

**What keeps it honest.**

- Every number comes from data cut at the constitution's `discovery_end`
  (2023-12-31): bars after it are dropped, not only entries. The selection year
  and the forward test are never shown to the model (issue #152).
- Every screen, IC and event study is an experiment-store row (`asked_by` the
  agent), so the record of what was searched grows with every look. Screens
  carry daily returns and so raise the firewall's noise bar.
- A rule already in the store is not screened again; its figures come back.
- At most `max_screens` screens and `max_looks` IC or event studies a run.
- A new feature is a formula in the language, checked by code for look-ahead
  (structurally and by cutting the data), coverage, determinism and likeness to
  what exists (`research/feature_registry.py`). No `exec`, no `eval`.
- No tool reaches the gate, the trial ledger or the order path. An agent reaches
  this module only through the runtime's `Context.converse`.

Nothing here decides anything. Cards the model writes at the end go through
the autopilot's parse, lesson and repeat checks, then the full screen over the
whole research window, as every other card does.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from collections.abc import Callable, Collection, Mapping
from datetime import date, datetime
from typing import Any

import numpy as np
from pydantic import BaseModel, ValidationError

from eulerlab.assistant import tools as assistant_tools
from eulerlab.assistant.tools import Tool
from eulerlab.features.formula import FormulaError, text_of
from eulerlab.intraday import rule_engine
from eulerlab.research import agenda, combine, experiments, feature_registry, lang, novelty

DEFAULT_SCREENS = 8
"""Screens one run may take. Each is a row in the store and so a little more bar."""
DEFAULT_LOOKS = 16
"""IC measurements and event studies one run may take."""
HORIZONS = (1, 5, 20)
PLACEBOS = 50
NEAREST_ROWS = 400
"""Past screens compared by daily returns, newest first, for the closest-rule line."""

EngineFactory = Callable[[date], Any]
"""Builds an engine whose data ends on the given day. Tests pass a fake."""

_OBJECT = {"type": "object", "properties": {}}


def discovery_engine(end: date) -> rule_engine.Engine:
    """The research data with every bar after `end` dropped, scored by the fast evaluator.

    Cutting only the entry window would still let a swing entered in December
    2023 exit on a 2024 price, so the panel itself stops at `end`."""
    from eulerlab.research import fast_eval

    data = rule_engine.Data()
    data.panel = {
        symbol: {d: bar for d, bar in bars.items() if d <= end}
        for symbol, bars in data.panel.items()
    }
    data.sessions = [d for d in data.sessions if d <= end]
    data.index = {d: i for i, d in enumerate(data.sessions)}
    data.end = min(data.end, end)
    return fast_eval.FastEngine(data)


def _sharpe(block: Mapping[str, Any] | None) -> Any:
    return (block or {}).get("sharpe")


def brief(screen: Mapping[str, Any]) -> dict[str, Any]:
    """The figures a researcher reads first, from the engine's screen output."""
    years = screen.get("net_by_year") or {}
    positive = [y for y, v in years.items() if (v or {}).get("total_return", 0) > 0]
    return {
        "count": screen.get("count"),
        "net_bps_each": (screen.get("per_bps") or {}).get("net_mean"),
        "gross_bps_each": (screen.get("per_bps") or {}).get("gross_mean"),
        "net_sharpe": _sharpe(screen.get("net")),
        "halves_sharpe": [
            _sharpe((screen.get("halves") or {}).get("first")),
            _sharpe((screen.get("halves") or {}).get("second")),
        ],
        "sharpe_at_2x_costs": _sharpe(screen.get("net_at_2x_costs")),
        "years_positive": f"{len(positive)} of {len(years)}",
        "flags": [c.get("check") for c in screen.get("checks") or [] if c.get("flag")],
        "passes_screen": screen.get("passes_screen"),
        "clean": screen.get("clean"),
    }


class ResearchTools:
    """One run's tools. Holds its counts, the engine it loaded and what it found."""

    def __init__(
        self,
        *,
        asked_by: str,
        discovery_end: date,
        now: datetime,
        max_screens: int = DEFAULT_SCREENS,
        max_looks: int = DEFAULT_LOOKS,
        engine: EngineFactory = discovery_engine,
        ideas: novelty.Seen | None = None,
    ) -> None:
        self.asked_by = asked_by
        self._ideas = ideas
        """Idea keys tried before this run (ADR-209); read at the first screen when not given."""
        self.discovery_end = discovery_end
        self.now = now
        self.max_screens = max_screens
        self.max_looks = max_looks
        self._factory = engine
        self._engine: Any = None
        self.screened: list[dict[str, Any]] = []
        """Every screen this run took, in order: fingerprint, rule, family, figures."""
        self.looks: list[dict[str, Any]] = []
        """Every IC measurement and event study this run took."""
        self.features: list[dict[str, Any]] = []
        """Every feature this run defined, kept or refused."""
        self.questions: set[str] = set()
        """Agenda questions this run asked or wrote a finding on."""
        self.calls: Counter[str] = Counter()
        spec_arg = {
            "type": "object",
            "properties": {"spec": {"type": "object", "description": "The spec."}},
            "required": ["spec"],
        }
        formula_arg = {
            "type": "object",
            "properties": {
                "formula": {"type": "string", "description": "A language-v2 expression."},
                "horizons": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": f"Sessions ahead, 1 to 60. Default {list(HORIZONS)}.",
                },
            },
            "required": ["formula"],
        }
        self.tools: dict[str, Tool] = {
            "language": Tool(
                "Language v2: every field (with the sessions that must pass before it may be "
                "read), every operator, the features agents have defined, and the spec shape "
                "for screen_formula. Call this first.",
                _OBJECT,
                self._language,
            ),
            "signals": Tool(
                "The old rule engine's eleven signals and its spec shape, for screen_rule.",
                _OBJECT,
                self._signals,
            ),
            "claim_record": assistant_tools.TOOLS["claim_record"],
            "family_record": Tool(
                "How each family of rules has done in the experiment store: rules tried, "
                "how many passed the screen and how many were clean. A family is the kind "
                "and the signals it uses, e.g. 'intraday:gap+results_morning'. Give words "
                "to filter, or none for all.",
                {
                    "type": "object",
                    "properties": {"match": {"type": "string", "description": "Part of a family."}},
                },
                self._family_record,
            ),
            "agenda": Tool(
                "The research agenda: open questions, least explored first, each with its "
                "findings so far and the next step. Pick one to work on.",
                _OBJECT,
                self._agenda,
            ),
            "ask_question": Tool(
                "Add a research question to the agenda (a falsifiable question about Indian "
                "stocks, not a rule). Returns its id.",
                {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "why": {
                            "type": "string",
                            "description": "The economic reason it might hold.",
                        },
                    },
                    "required": ["question", "why"],
                },
                self._ask_question,
            ),
            "record_finding": Tool(
                "Write what you learned about an agenda question, with the screens or looks "
                "behind it. Optionally close it (answered or dead) and name the next step.",
                {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "finding": {"type": "string"},
                        "status": {"type": "string", "enum": ["open", "answered", "dead"]},
                        "next_step": {"type": "string"},
                    },
                    "required": ["id", "finding"],
                },
                self._record_finding,
            ),
            "define_feature": Tool(
                "Define a new signal as a language-v2 formula, readable at the entry "
                "session's open. Code checks it for look-ahead, coverage, determinism and "
                "likeness to existing fields; a kept feature can be used by name in later "
                "formulas, by you and other agents.",
                {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "lowercase_with_underscores"},
                        "formula": {"type": "string"},
                        "why": {"type": "string", "description": "The economic reason."},
                    },
                    "required": ["name", "formula", "why"],
                },
                self._define_feature,
            ),
            "feature_ic": Tool(
                "Measure a formula's rank information coefficient against each stock's return "
                "from the entry open over the next h sessions, net of the day's average, on "
                "2016 to the discovery end. Recorded as a look; at most "
                f"{max_looks} looks a run.",
                formula_arg,
                self._feature_ic,
            ),
            "event_study": Tool(
                "Average return after an event, net of the day's average, at each horizon, "
                "with a placebo of as many random stock-sessions: the share of placebos the "
                "event beats. `formula` is the event: true where it happens. Recorded as a look.",
                formula_arg,
                self._event_study,
            ),
            "screen_rule": Tool(
                "Screen one rule in the old engine's spec (see `signals`) on 2016 to the "
                "discovery end: trades, net bps each, net Sharpe, halves, 2x costs, years "
                f"positive, bias flags, the closest past rule. At most {max_screens} screens a run.",
                spec_arg,
                self._screen_rule,
            ),
            "screen_formula": Tool(
                "Screen one language-v2 rule (see `language`): shape event or cross_section, "
                "kind, hold, side, when, score, top, every. Same figures as screen_rule and "
                "the same allowance.",
                spec_arg,
                self._screen_formula,
            ),
            "combine_signals": Tool(
                "Combine 2 to 20 weak signals (language-v2 formulas or features) into one "
                "walk-forward forecast, fitted each month only on the past (method ic or "
                "ridge), and trade only where it beats the round trip's cost (swing long "
                "only). Screened as one book with the same figures as screen_rule, plus "
                "turnover, cost share, the latest weights and each signal's IC by horizon. "
                "Uses one screen of the allowance.",
                {
                    "type": "object",
                    "properties": {
                        "formulas": {"type": "array", "items": {"type": "string"}},
                        "kind": {"type": "string", "enum": ["intraday", "swing"]},
                        "hold": {"type": "integer", "description": "swing: 2 to 60 sessions"},
                        "method": {"type": "string", "enum": ["ic", "ridge"]},
                    },
                    "required": ["formulas", "kind"],
                },
                self._combine_signals,
            ),
        }

    # --- the Toolbox protocol (`assistant.chat.ask`) ---------------------------------

    def schemas(self, names: Collection[str] | None = None) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {"name": n, "description": t.description, "parameters": t.parameters},
            }
            for n, t in self.tools.items()
            if names is None or n in names
        ]

    def call(self, name: str, raw_arguments: str) -> str:
        tool = self.tools.get(name)
        if tool is None:
            return f"There is no tool '{name}'. Tools: {', '.join(self.tools)}."
        try:
            args = json.loads(raw_arguments) if raw_arguments.strip() else {}
        except json.JSONDecodeError:
            return "The arguments were not valid JSON."
        if not isinstance(args, dict):
            args = {}
        self.calls[name] += 1
        try:
            return assistant_tools._clip(tool.run(args))
        except Exception as exc:  # a broken tool tells the model; it does not end the run
            return f"{name} failed: {type(exc).__name__}: {str(exc)[:200]}"

    # --- the engine, cut at the discovery end ----------------------------------------

    def engine(self) -> Any:
        if self._engine is None:
            self._engine = self._factory(self.discovery_end)
        found = self._engine
        if not found.data.sessions or found.data.sessions[-1] > self.discovery_end:
            last = found.data.sessions[-1] if found.data.sessions else "nothing"
            msg = f"the loop's data reaches {last}, after the discovery end {self.discovery_end}"
            raise experiments.SealedPeriod(msg)
        return found

    def _last(self) -> date:
        found: rule_engine.Engine = self.engine()
        return min(found.data.end, found.data.sessions[-1])

    def _store(self) -> Any:
        found = self.engine()
        if not hasattr(found, "store"):
            msg = "this engine has no feature tables (a FastEngine is needed)"
            raise TypeError(msg)
        return found.store

    # --- reading tools -----------------------------------------------------------------

    def _language(self, _: Mapping[str, Any]) -> str:
        return (
            f"{lang.describe()}\n\n{feature_registry.describe()}\n\n"
            'A screen_formula spec: {"shape": "event" | "cross_section", "kind": '
            '"intraday" | "swing", "hold": 0 intraday or 2-60 swing, "side": "long" | '
            '"short" (intraday only) | "against" | "with" (with "side_by": an expression), '
            '"when": an expression true on entry (event), "score": an expression, higher '
            'first, "top": 1-10, "every": 1-20 sessions (cross_section)}. Entry is at the '
            "session's official open; a field decided by a close needs delay(..., 1)."
        )

    def _signals(self, _: Mapping[str, Any]) -> str:
        from eulerlab.agents.workers import autopilot

        return f"Signals:\n{autopilot.vocabulary()}\n\n{autopilot.SPEC_HELP}"

    def _family_record(self, args: Mapping[str, Any]) -> str:
        match = str(args.get("match") or "").strip().lower()
        tally: dict[str, Counter[str]] = {}
        for row in experiments.rows(purpose="screen"):
            family = str(row.get("family") or "")
            if match and match not in family.lower():
                continue
            metrics = row.get("metrics") or {}
            t = tally.setdefault(family, Counter())
            t["tried"] += 1
            t["passed"] += bool(metrics.get("passes_screen"))
            t["clean"] += bool(metrics.get("clean"))
        if not tally:
            return "No screens recorded" + (f" for families like '{match}'." if match else ".")
        lines = [
            f"{f}: {c['tried']} tried, {c['passed']} passed the screen, {c['clean']} clean"
            for f, c in sorted(tally.items(), key=lambda x: -x[1]["tried"])
        ]
        return "Source: data/derived/experiments.jsonl (screens)\n" + "\n".join(lines)

    # --- the agenda --------------------------------------------------------------------

    def _agenda(self, _: Mapping[str, Any]) -> str:
        return agenda.summary()

    def _ask_question(self, args: Mapping[str, Any]) -> str:
        qid = agenda.ask(
            str(args.get("question") or ""),
            str(args.get("why") or ""),
            author=self.asked_by,
            now=self.now,
        )
        self.questions.add(qid)
        return f"On the agenda as {qid}."

    def _record_finding(self, args: Mapping[str, Any]) -> str:
        status = args.get("status")
        refs = [s["fingerprint"] for s in self.screened] + [x["id"] for x in self.looks]
        q = agenda.note(
            str(args.get("id") or ""),
            str(args.get("finding") or ""),
            author=self.asked_by,
            refs=refs,
            status=status if status in agenda.STATUSES else None,
            next_step=str(args.get("next_step") or ""),
            now=self.now,
        )
        self.questions.add(q.id)
        return f"Recorded. {q.line()}"

    # --- features and measurements -----------------------------------------------------

    def _define_feature(self, args: Mapping[str, Any]) -> str:
        store = self._store()
        name = str(args.get("name") or "").strip()
        found = feature_registry.define(
            name,
            str(args.get("formula") or ""),
            str(args.get("why") or ""),
            author=self.asked_by,
            panel=store,
            tradable=store.tradable,
            now=self.now,
        )
        self.features.append({"name": name, "kept": found["ok"], **found})
        if not found["ok"]:
            return f"Refused: {found['why']}. Checks: {json.dumps(found['checks'], default=str)}"
        return (
            f"Kept {name} = {found['formula']}. Checks: {json.dumps(found['checks'], default=str)}. "
            "Use it by name in formulas."
        )

    def _compile(self, formula: str) -> Any:
        return lang.compile_text(feature_registry.expand(formula))

    def _horizons(self, args: Mapping[str, Any]) -> list[int]:
        raw = args.get("horizons") or list(HORIZONS)
        out = sorted({int(h) for h in raw if 1 <= int(h) <= 60}) if isinstance(raw, list) else []
        return out[:4] or list(HORIZONS)

    def _look(self, kind: str, formula: str, horizons: list[int], metrics: dict[str, Any]) -> str:
        """Record an IC or event study as an experiment row (no daily returns). Returns its id."""
        fields = sorted(set(lang.complexity([lang.compile_text(formula)])["fields"]))
        fp = hashlib.sha256(f"{kind}|{formula}|{horizons}".encode()).hexdigest()[:16]
        row = experiments.record(
            purpose="screen",
            fingerprint=fp,
            family=f"{kind}:{'+'.join(fields)}",
            first=rule_engine.FIRST,
            end=self._last(),
            metrics={"look": kind, "formula": formula, **metrics, "explore": True},
            asked_by=self.asked_by,
            now=self.now,
        )
        self.looks.append({"id": row, "kind": kind, "formula": formula, **metrics})
        return row

    def _feature_ic(self, args: Mapping[str, Any]) -> str:
        if len(self.looks) >= self.max_looks:
            return f"This run has used its {self.max_looks} looks."
        try:
            tree = self._compile(str(args.get("formula") or ""))
        except FormulaError as exc:
            return f"The formula does not compile: {exc}"
        store = self._store()
        score = lang.Evaluator(store).value(tree)
        score = np.where(store.tradable, score, np.nan)
        found = [
            combine.information_coefficient(score, combine.forward_returns(store, h), h)
            for h in self._horizons(args)
        ]
        text = text_of(tree)
        self._look("ic", text, [f["horizon"] for f in found], {"ic": found})
        return (
            f"IC of {text} on {store.days[0]} to {self._last()} (discovery only):\n"
            + "\n".join(json.dumps(f) for f in found)
            + "\nRough guide: |mean IC| under 0.02 rarely pays a 12 bps round trip alone."
        )

    def _event_study(self, args: Mapping[str, Any]) -> str:
        if len(self.looks) >= self.max_looks:
            return f"This run has used its {self.max_looks} looks."
        try:
            tree = self._compile(str(args.get("formula") or ""))
        except FormulaError as exc:
            return f"The formula does not compile: {exc}"
        store = self._store()
        truth = lang._truth(lang.Evaluator(store).value(tree)) & store.tradable
        text = text_of(tree)
        rng = random.Random(int(hashlib.sha256(text.encode()).hexdigest()[:8], 16))
        rows: list[dict[str, Any]] = []
        for h in self._horizons(args):
            ahead = combine.forward_returns(store, h)
            hit = truth & ~np.isnan(ahead)
            n = int(hit.sum())
            if n < 30:
                rows.append({"horizon": h, "events": n, "note": "under 30 events"})
                continue
            mean = float(ahead[hit].mean())
            by_day = [float(ahead[t, hit[t]].mean()) for t in range(hit.shape[0]) if hit[t].any()]
            sd = float(np.std(by_day, ddof=1)) if len(by_day) > 2 else 0.0
            t_stat = mean / sd * np.sqrt(len(by_day)) if sd > 0 else None
            pool = np.flatnonzero((store.tradable & ~np.isnan(ahead)).ravel())
            flat = ahead.ravel()
            draw = min(n, len(pool))
            placebo = [
                float(flat[pool[np.array(rng.sample(range(len(pool)), draw))]].mean())
                for _ in range(PLACEBOS)
            ]
            beats = float(np.mean([abs(mean) > abs(p) for p in placebo]))
            rows.append(
                {
                    "horizon": h,
                    "events": n,
                    "days": len(by_day),
                    "mean_bps": round(mean * 1e4, 1),
                    "t_stat_by_day": round(float(t_stat), 2) if t_stat is not None else None,
                    "beats_placebo_share": round(beats, 2),
                }
            )
        self._look("event", text, [r["horizon"] for r in rows], {"event": rows})
        return (
            f"Event study of {text} on {store.days[0]} to {self._last()} (discovery only), "
            "returns from the entry open net of the day's average:\n"
            + "\n".join(json.dumps(r) for r in rows)
            + f"\nbeats_placebo_share: the share of {PLACEBOS} random draws of as many stock-"
            "sessions whose mean is smaller in size. Under 0.95 is not evidence."
        )

    def _combine_signals(self, args: Mapping[str, Any]) -> str:
        formulas = [str(f) for f in args.get("formulas") or [] if str(f).strip()]
        kind: combine.Kind = "intraday" if args.get("kind") == "intraday" else "swing"
        hold = 0 if kind == "intraday" else int(args.get("hold") or 5)
        method: combine.Method = "ridge" if args.get("method") == "ridge" else "ic"
        if len(self.screened) >= self.max_screens:
            return f"This run has used its {self.max_screens} screens. Write the cards now."
        try:
            found = combine.combine(self.engine(), formulas, kind=kind, hold=hold, method=method)
        except (FormulaError, ValueError) as exc:
            return f"Could not combine: {exc}"[:600]
        rule = found["rule"]
        fp = rule.fingerprint()
        for row in experiments.rows(purpose="screen"):
            if row.get("fingerprint") == fp:
                return (
                    "Already screened: " + json.dumps(row.get("metrics") or {}, default=str)[:1500]
                )
        figures = combine.summary(found)
        combine.record(found, asked_by=self.asked_by, now=self.now)
        self.screened.append(
            {"fingerprint": fp, "rule": rule.describe(), "family": "combined", **figures}
        )
        return (
            f"Window: out of sample from {rule.first} to {self._last()} (discovery only)\n"
            + json.dumps(figures, default=str)
            + f"\n{self.max_screens - len(self.screened)} screen(s) left this run. A combined "
            "book cannot be a card yet; say in a finding which signals it used."
        )

    # --- screens -----------------------------------------------------------------------

    def _screen_rule(self, args: Mapping[str, Any]) -> str:
        raw = _spec_arg(args)
        if isinstance(raw, str):
            return raw
        try:
            spec = rule_engine.RuleSpec.model_validate(raw)
        except ValidationError as exc:
            return f"The spec does not parse: {exc.errors()[0].get('msg', 'invalid')}"
        return self._screen(spec)

    def _screen_formula(self, args: Mapping[str, Any]) -> str:
        raw = _spec_arg(args)
        if isinstance(raw, str):
            return raw
        try:
            spec = parse_formula_spec(raw)
        except (ValidationError, FormulaError, ValueError) as exc:
            return f"The spec does not parse: {exc}"[:600]
        return self._screen(spec)

    def _screen(self, spec: rule_engine.Rule) -> str:
        from eulerlab.research.autopilot import family_of  # the coverage-map cell, one definition

        fp = spec.fingerprint()
        for row in experiments.rows(purpose="screen"):
            if row.get("fingerprint") == fp:
                return (
                    f"Already screened ({row.get('asked_by')}, {row.get('at')}, window "
                    f"{row.get('first')} to {row.get('end')}): "
                    + json.dumps(row.get("metrics") or {}, default=str)[:1500]
                    + "\nNot screened again. Try a different rule."
                )
        key = novelty.rule_key(spec)
        if self._ideas is None:
            self._ideas = novelty.seen()
        twin = self._ideas.keys.get(key)
        if twin is not None:
            return (
                f"Not screened: the same idea as {twin} with other numbers. A different "
                "threshold, window, lag or hold is tuning and spends a trial on nothing new. "
                "Try a different idea."
            )
        mine = next((s for s in self.screened if s.get("idea") == key), None)
        if mine is not None:
            return (
                f"Not screened: you screened this idea this run already ({mine['rule']}). "
                "Screening it again with other numbers is tuning. Try a different idea."
            )
        if len(self.screened) >= self.max_screens:
            return f"This run has used its {self.max_screens} screens. Write the cards now."
        engine = self.engine()
        last = self._last()
        out = engine.screen(spec)
        daily = engine.returns.pop(fp, None)
        figures = brief(out)
        figures["closest_past_rule"] = nearest(daily or {})
        experiments.record(
            purpose="screen",
            hypothesis="",
            fingerprint=fp,
            family=family_of(spec),
            first=spec.first,
            end=last,
            metrics={**figures, "explore": True},
            daily=daily,
            asked_by=self.asked_by,
            now=self.now,
            spec=spec.model_dump(mode="json") if isinstance(spec, BaseModel) else None,
        )
        self.screened.append(
            {
                "fingerprint": fp,
                "rule": spec.describe(),
                "family": family_of(spec),
                "idea": key,
                **figures,
            }
        )
        left = self.max_screens - len(self.screened)
        return (
            f"Rule: {spec.describe()}\nWindow: {spec.first} to {last} (discovery only)\n"
            + json.dumps(figures, default=str)
            + f"\n{left} screen(s) left this run."
        )


def _spec_arg(args: Mapping[str, Any]) -> Any:
    raw = args.get("spec")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return "The spec was not valid JSON."
    return raw


def parse_formula_spec(raw: Any) -> lang.Spec:
    """A language-v2 spec with every agent-defined feature expanded to its formula."""
    if not isinstance(raw, dict):
        msg = "a spec is a JSON object"
        raise ValueError(msg)
    body = dict(raw)
    for key in ("when", "score", "side_by"):
        if isinstance(body.get(key), str):
            body[key] = feature_registry.expand(body[key])
    return lang.Spec.model_validate(body)


def _correlation(a: Mapping[date, float], b: Mapping[date, float]) -> float | None:
    days = [d for d in a if d in b]
    if len(days) < 60:
        return None
    x = np.array([a[d] for d in days])
    y = np.array([b[d] for d in days])
    if x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def nearest(daily: Mapping[date, float]) -> dict[str, Any] | None:
    """The past screen whose daily returns move most with these, among the newest few hundred."""
    if not daily:
        return None
    best: dict[str, Any] | None = None
    seen: set[str] = set()
    for row in reversed(experiments.rows(purpose="screen")):
        if len(seen) >= NEAREST_ROWS:
            break
        key = str(row.get("fingerprint"))
        if key in seen or not row.get("returns"):
            continue
        seen.add(key)
        c = _correlation(daily, experiments.returns_of(row))
        if c is not None and (best is None or abs(c) > abs(best["correlation"])):
            best = {
                "fingerprint": key,
                "card": row.get("hypothesis") or "",
                "family": row.get("family"),
                "correlation": round(c, 2),
                "net_sharpe": (row.get("metrics") or {}).get("net_sharpe"),
            }
    return best
