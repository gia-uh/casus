# Slice 7 — evaluate mode

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person opens a study (every run of one version of one scenario), adds runs knowing what they cost, reads the runs side by side on one chart, and asks the evaluate agent questions whose every figure is checked against what its queries returned.

**Architecture:** `studies.py` groups `runs/` by a digest of the scenario data and rules source each transcript carries. `evaluate/queries.py` holds the fixed queries (plain dicts plus a compact text for the model) and `evaluate/checker.py` the figure check; neither imports lovelaice. `evaluate/tools.py` and `evaluate/agent.py` wrap them in nine lovelaice tools and an agent built exactly as slice 6 builds the design agent. `RunManager.start_batch` reuses slice 3's run machinery behind a semaphore. `server/study.py` is the router, built like slice 6's `server/design.py`; `ui/js/study.js` is the screen and the home shelf's study actions.

**Tech Stack:** Python 3.13, FastAPI, PyYAML, lovelaice 2.13.1 on lingo-ai 2.1 (a normal dependency), plain JS, pytest, node, Playwright.

**Specs:** `docs/specs/2026-09-29-evaluate-mode-design.md` (all of it) and `docs/specs/2026-09-28-interface-design.md` ("The shell", "The study (evaluate mode)"). Master plan: `docs/plans/2026-09-29-casus-app-plan.md`; its contracts are binding. Slice 1's plan is the format and the source of `studies.py`, `create_app`, `shell.js`, `app.css`, the JS harness and the browser fixtures.

**Reference for the look:** the mockup's `estudio()` and its CSS (`.split2`, `.agent`, `.log`, `.tool`, `.study`, `.runs`, `.runc`, `.chartbox`) in `/home/apiad/Workspace/vault/Efforts/Areas/University/casus-clase/mockups/casus-v2.html`. Slice 1 already copied that CSS into `ui/css/app.css`. Copy no data from the mockup. The mockup put a run with the original rules and a run with the recovery rules in one study; this slice's study key is what stops that (Task 1).

## What this slice uses from slices 3, 5 and 6

Slice 7 depends on slices 3 and 5. It uses these names exactly as their plans define them; if an implementation differs, use the implemented name and say so in the PR.

- **Slice 3** (`docs/plans/2026-09-29-slice-3-live-runs.md`): `RunManager(runs_dir, engine_factory: Callable[[str], Engine] = engine.engine_for)` and its internals `self._runs: dict[str, _Run]`, `_Run()` with `.task` and `async .finish()`, `self._reserve(name, seed) -> Path` (creates `<name>-<seed>.jsonl` empty, or `-2`, `-3`… when taken), and `async self._play(run, scenario, path, seed, turns, engines, narrator)`. `create_app(*, scenarios_dir, runs_dir, settings=None, run_manager=None)`, whose body holds the manager in a local `manager`. `server/sse.py`: `event_stream(messages)` and `CLOSE`. Every failure ends a transcript with an `error` record (slice 3 Task 2). In `tests/helpers.py`: `RAIDING` and `LiveEngine`. `tests/browser/browser_support.serve(runs_dir, **app_kwargs)` passes `run_manager=` through.
- **Slice 5** (`docs/plans/2026-09-29-slice-5-settings.md`): `Settings.load(path=None, env=None)` with `agent_model`, `run_concurrency` (default 4), `endpoint`, `api_key`; `casus.settings.redact(text, secrets=None)` around any exception text shown or recorded.
- **Slice 6** (`docs/plans/2026-09-29-slice-6-design-mode.md`), in either order: the evaluate agent is built the way slice 6's Tasks 4 and 5 build the design agent (`build_*_agent(target, settings, session_dir) -> *Agent` with `async turn(text, send) -> str`, tools returning `ToolResult`s, the model faked by monkeypatching `lovelaice.agent.agent._build_llm`), and the router is shaped like `server/design.py` (a lock per target, `session_dir()`, a queue drained into the event stream, `done` sent after the lock is free). Both slices add the same `lovelaice` dependency; whichever lands second finds it present (Task 6).

## Global Constraints

Everything in the master plan's Global Constraints, plus:

- A study is one scenario name and one version. Nothing groups runs of two versions, and a batch only adds runs of the scenario's current version.
- The language model never computes a quantity, and in this slice it never states one unchecked: after every answer the server runs `unsupported_numbers` over the answer and every tool result of the session, and the `done` message carries the result. The browser only draws the marks; it never decides what is supported.
- The evaluate agent runs no code. Its tools are exactly the nine in `evaluate.tools.TOOL_NAMES`; none takes a path.
- Only `evaluate/tools.py` and `evaluate/agent.py` import lovelaice at module level. `studies.py`, `evaluate/queries.py`, `evaluate/checker.py`, `server/study.py` and `server/app.py` do not, which keeps the engine core and the queries free of the agent's I/O; `test_queries_checker_and_the_server_import_without_lovelaice` holds it.
- A study's chat lives under the user's data directory (`$XDG_DATA_HOME/casus/sessions/studies/<scenario>-<version>.jsonl`, default `~/.local/share`), never under `runs/`.
- Exception text shown in the chat goes through `casus.settings.redact`.

## Review Focus

Owned by this slice:

- Two versions never share a study, and a scenario loaded from YAML digests like its transcript copy: `tests/test_studies.py::test_changing_one_coefficient_in_the_rules_splits_the_study` and `::test_a_loaded_scenario_has_the_version_its_transcripts_carry`.
- A figure that is only in the question, or that the model derived, is flagged: `tests/test_evaluate_checker.py::test_a_number_only_in_the_question_is_flagged` and `::test_a_derived_difference_is_flagged`.
- A batch never exceeds its concurrency, and one failed run neither stops the batch nor vanishes: `tests/test_evaluate_batches.py::test_the_concurrency_limit_holds` and `::test_a_failing_run_is_recorded_and_the_batch_goes_on`.
- Seed 1 of a new version never overwrites seed 1 of an old one: `tests/test_evaluate_batches.py::test_a_seed_already_on_disk_gets_its_own_file`.

---

### Before Task 1: the branch and what it stands on

- [ ] **Step 1: Cut the branch**

```bash
git fetch origin
git worktree add .claude/worktrees/5-slice-7-evaluate-mode \
  -b 5-slice-7-evaluate-mode origin/main
cd .claude/worktrees/5-slice-7-evaluate-mode
uv sync
```

- [ ] **Step 2: Check that slices 3 and 5 are in**

Run: `grep -n "def _reserve\|async def _play\|self._runs\|class _Run" src/casus/server/runs.py; grep -n "run_manager" src/casus/server/app.py; grep -n "^def redact\|run_concurrency" src/casus/settings.py`
Expected: each name appears. If one does not, stop: this slice cannot start before slices 3 and 5 are merged.

---

### Task 1: Studies, one version of one scenario

**Files:**
- Modify: `src/casus/studies.py`
- Create: `tests/evaluate_support.py`
- Test: `tests/test_studies.py`

**Interfaces:**
- Consumes: `RunInfo`, `list_runs` (slice 1); `engine.run`, `Scenario.load`, `Scenario.from_parts`; `helpers.RAIDING` (slice 3).
- Produces: `version_of(scenario_record: dict) -> str` (12 hex characters), `Study(scenario, version, runs)` with `.to_json()`, `list_studies(runs_dir) -> list[Study]` (master plan). In `tests/evaluate_support.py`: `SMOKE`, `SEEDS`, `TURNS`, `record_study(runs_dir, seeds=SEEDS, turns=TURNS, rules=None, data=None) -> Study`, `records(study) -> dict[str, list[dict]]`.

`version_of` digests the scenario data after one JSON round trip. The transcript stores the data as JSON, where a YAML key like `display.bands`' `10` becomes `"10"`; sorting `5, 10` and `"10", "5"` gives different orders, so without the round trip a freshly loaded scenario and its own transcript would disagree about their version.

- [ ] **Step 1: Write the test support**

Create `tests/evaluate_support.py`:

```python
"""A small recorded study the evaluate tests share: smoke runs in which Blue
raids the border at full intensity every turn (`helpers.RAIDING`) and Red
holds, so the border's infrastructure only ever falls."""

from __future__ import annotations

import pathlib

from casus import engine, studies
from casus.scenario import Scenario
from helpers import RAIDING, FakeEngine

ROOT = pathlib.Path(__file__).parent.parent
SMOKE = ROOT / "scenarios" / "smoke"
SEEDS = (1, 2, 3)
TURNS = 3


def record_study(
    runs_dir: pathlib.Path, seeds=SEEDS, turns=TURNS, rules=None, data=None
) -> studies.Study:
    """Record one smoke run per seed into `runs_dir` and return their study."""
    scenario = Scenario.load(SMOKE)
    if rules is not None or data is not None:
        scenario = Scenario.from_parts(data or scenario.data, rules or scenario.rules_source)
    for seed in seeds:
        engines = {a: FakeEngine(RAIDING) for a in scenario.actors}
        out = runs_dir / f"smoke-{seed}.jsonl"
        engine.run(scenario, seed=seed, out=out, engines=engines, turns=turns)
    [study] = [s for s in studies.list_studies(runs_dir) if s.runs[0].seed in seeds]
    return study


def records(study: studies.Study) -> dict[str, list[dict]]:
    """Each run's records, read straight from the file."""
    return {info.id: engine.read_records(info.path) for info in study.runs}
```

- [ ] **Step 2: Write the failing tests**

In `tests/test_studies.py`, add to the imports:

```python
import yaml
from evaluate_support import record_study
```

and append:

```python
# --- studies: runs grouped by version (slice 7) ----------------------------------


def test_runs_of_the_same_data_and_rules_are_one_study(tmp_path):
    record_study(tmp_path, seeds=(1, 2))
    [study] = studies.list_studies(tmp_path)
    assert (study.scenario, [r.seed for r in study.runs]) == ("smoke", [1, 2])
    assert len(study.version) == 12 and int(study.version, 16) >= 0


def test_changing_one_coefficient_in_the_rules_splits_the_study(tmp_path):
    rules = (SMOKE / "rules.py").read_text()
    assert "RAID_DAMAGE = 5.0" in rules
    record_study(tmp_path, seeds=(1,))
    record_study(
        tmp_path, seeds=(2,), rules=rules.replace("RAID_DAMAGE = 5.0", "RAID_DAMAGE = 6.0")
    )
    found = studies.list_studies(tmp_path)
    assert len(found) == 2 and found[0].version != found[1].version
    assert sorted(r.seed for s in found for r in s.runs) == [1, 2]


def test_a_loaded_scenario_has_the_version_its_transcripts_carry(tmp_path):
    """YAML mapping keys may be numbers (`display.bands`); a transcript stores
    them as strings, which sort differently (5 < 10, but "10" < "5"). The
    version must not depend on which copy was digested."""
    data = yaml.safe_load((SMOKE / "scenario.yaml").read_text())
    data["display"]["bands"] = {
        "supplies": {5: "short", 10: "adequate", float("inf"): "plenty"}
    }
    study = record_study(tmp_path, seeds=(1,), data=data)
    rules = (SMOKE / "rules.py").read_text()
    assert studies.version_of({"scenario": data, "rules_source": rules}) == study.version


def test_versions_are_listed_newest_first(tmp_path):
    rules = (SMOKE / "rules.py").read_text()
    record_study(tmp_path, seeds=(1,))
    record_study(
        tmp_path, seeds=(2,), rules=rules.replace("RAID_DAMAGE = 5.0", "RAID_DAMAGE = 6.0")
    )
    for seed, ts in ((1, 2000.0), (2, 1000.0)):
        path = tmp_path / f"smoke-{seed}.jsonl"
        lines = path.read_text().splitlines()
        header = json.loads(lines[0]) | {"ts": ts}
        path.write_text("\n".join([json.dumps(header), *lines[1:]]) + "\n")
    assert [s.runs[0].seed for s in studies.list_studies(tmp_path)] == [1, 2]


def test_a_study_serialises_its_runs(tmp_path):
    study = record_study(tmp_path, seeds=(1,))
    as_json = study.to_json()
    assert as_json["runs"][0]["id"] == "smoke-1" and as_json["version"] == study.version


def test_a_file_whose_header_lacks_the_rules_is_in_no_study(tmp_path):
    record_study(tmp_path, seeds=(1,))
    (tmp_path / "odd.jsonl").write_text(json.dumps({"kind": "scenario", "name": "odd"}) + "\n")
    assert [s.scenario for s in studies.list_studies(tmp_path)] == ["smoke"]
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_studies.py -q`
Expected: FAIL with `AttributeError: module 'casus.studies' has no attribute 'list_studies'`.

- [ ] **Step 4: Implement**

In `src/casus/studies.py`, add `import hashlib` to the imports and append:

```python
# --- studies (slice 7) ------------------------------------------------------


def version_of(scenario_record: dict) -> str:
    """The version a run played: 12 hex characters of a sha256 over the scenario
    data and the rules source, as canonical JSON.

    The data makes one JSON round trip first, so a scenario freshly loaded from
    YAML, whose mapping keys may be numbers (as in `display.bands`), digests the
    same as the copy its transcript carries."""
    data = json.loads(json.dumps(scenario_record["scenario"], ensure_ascii=False))
    canonical = json.dumps(
        {"scenario": data, "rules_source": scenario_record["rules_source"]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


@dataclasses.dataclass(frozen=True)
class Study:
    scenario: str
    version: str
    runs: tuple[RunInfo, ...]

    def to_json(self) -> dict:
        return {
            "scenario": self.scenario,
            "version": self.version,
            "runs": [r.to_json() for r in self.runs],
        }


def _header(path: pathlib.Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    record = json.loads(line)
                    return record if record.get("kind") == "scenario" else None
    except (OSError, json.JSONDecodeError):
        return None
    return None


def list_studies(runs_dir: pathlib.Path) -> list[Study]:
    """The runs under `runs_dir` grouped by scenario name and version. Scenarios
    in name order; a scenario's versions newest first, by the newest run in
    each; a study's runs by seed."""
    groups: dict[tuple[str, str], list[RunInfo]] = {}
    newest: dict[tuple[str, str], float] = {}
    for info in list_runs(runs_dir):
        header = _header(info.path)
        if header is None or "scenario" not in header or "rules_source" not in header:
            continue
        key = (info.scenario, version_of(header))
        groups.setdefault(key, []).append(info)
        newest[key] = max(newest.get(key, 0.0), float(header.get("ts", 0.0)))
    order = sorted(groups, key=lambda k: (k[0], -newest[k]))
    return [
        Study(
            scenario=name,
            version=version,
            runs=tuple(sorted(groups[(name, version)], key=lambda r: (r.seed, r.id))),
        )
        for name, version in order
    ]
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_studies.py -q`
Expected: PASS (10 tests: slice 1's four and these six).

- [ ] **Step 6: Break it on purpose**

Replace `data = json.loads(json.dumps(scenario_record["scenario"], ensure_ascii=False))` with `data = scenario_record["scenario"]`. Run `uv run pytest tests/test_studies.py -q -k loaded_scenario`. Expected: FAIL (the two digests differ). Revert.

- [ ] **Step 7: Commit**

```bash
git add src/casus/studies.py tests/evaluate_support.py tests/test_studies.py
git commit -m "feat(studies): a study is one version of one scenario"
```

---

### Task 2: The figure checker

**Files:**
- Create: `src/casus/evaluate/__init__.py`, `src/casus/evaluate/checker.py`
- Test: `tests/test_evaluate_checker.py`

**Interfaces:**
- Produces: `unsupported_numbers(answer: str, tool_results: list[str]) -> list[str]` (master plan), and `figures(text) -> list[Figure]` with `Figure(text, readings, percent)`.

What counts as a figure is decided in the module docstring and pinned by the tests: digits inside a word or an identifier (`qwen3`, `3rd`, `2º`, `smoke-4`, a hex version), dotted versions (`2.13.1`) and list-item numbers at the start of a line are not figures; years, day numbers and counts are. Day numbers and run counts are nearly always supported, because every series lists its turns and `list_runs` states the count. A year no query returned came from the model's memory, and the room should see that. The sign is not checked, because prose carries it in words ("fell by 15.8"). A plain space never joins digit groups: "day 3 100 units" is two figures.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_evaluate_checker.py`:

```python
"""The check on an answer's figures: every one must come from a tool result."""

import pytest

from casus.evaluate.checker import figures, unsupported_numbers


def test_an_integer_matches_a_value_that_rounds_to_it():
    assert unsupported_numbers("It ended at 22.", ["value 22.0075"]) == []


def test_a_decimal_comma_matches_at_one_decimal():
    assert unsupported_numbers("terminó en 22,1", ["22.13"]) == []


def test_more_precision_than_the_tool_returned_is_flagged():
    assert unsupported_numbers("it ended at 22.13", ["22.1"]) == ["22.13"]


def test_a_wrong_rounding_is_flagged():
    assert unsupported_numbers("it ended at 23", ["22.0075"]) == ["23"]


def test_half_way_matches_both_neighbours():
    assert unsupported_numbers("22 and 23", ["22.5"]) == []


@pytest.mark.parametrize("text", ["1,234.5", "1.234,5", "1 234,5", "1 234.5"])
def test_thousands_separators_are_normalised(text):
    assert unsupported_numbers(f"about {text} tonnes", ["1234.5"]) == []


def test_a_lone_three_digit_group_reads_either_way():
    assert unsupported_numbers("1,234 left", ["1234"]) == []
    assert unsupported_numbers("1,234 left", ["1.234"]) == []
    assert unsupported_numbers("1,234 left", ["12.34"]) == ["1,234"]


def test_a_plain_space_does_not_join_two_figures():
    assert unsupported_numbers("on day 3 100 units moved", ["3", "100"]) == []


@pytest.mark.parametrize("text", ["45%", "45 %", "45,0 %"])
def test_a_percentage_matches_the_figure_or_the_fraction(text):
    assert unsupported_numbers(f"{text} of runs", ["45"]) == []
    assert unsupported_numbers(f"{text} of runs", ["0.45"]) == []
    assert unsupported_numbers(f"{text} of runs", ["0.46"]) == [text]


def test_the_sign_is_carried_by_the_words():
    assert unsupported_numbers("it fell by 15.8", ["change -15.79"]) == []


def test_a_derived_difference_is_flagged():
    answer = "It fell from 70 to 25.8, a drop of 44.2 points."
    assert unsupported_numbers(answer, ["70", "54.21", "39.36", "25.78"]) == ["44.2"]


def test_a_number_only_in_the_question_is_flagged():
    question_number = "57"
    answer = f"It stayed under {question_number} in every run."
    assert unsupported_numbers(answer, ["70 54.21 39.36"]) == [question_number]


@pytest.mark.parametrize(
    "text",
    [
        "qwen3 answered",
        "the 3rd run",
        "el 2º día",
        "run smoke-4 failed",
        "version 3a9f1c2b7d10",
        "data t0.02",
        "ref actor.BLUE.stamina",
    ],
)
def test_digits_inside_words_and_identifiers_are_not_figures(text):
    assert unsupported_numbers(text, []) == []


def test_list_item_numbers_are_not_figures():
    answer = "1. The raid rule lowers it.\n2) Nothing raises it.\n- 3. still a list"
    assert unsupported_numbers(answer, []) == []


def test_a_number_after_a_list_marker_is_still_a_figure():
    assert unsupported_numbers("1. It ended at 23.", ["22"]) == ["23"]


def test_years_are_figures():
    assert unsupported_numbers("as in the 1962 crisis", ["70"]) == ["1962"]


def test_each_unsupported_figure_is_listed_once_in_order():
    assert unsupported_numbers("9, then 8, then 9 again", []) == ["9", "8"]


def test_numbers_in_identifiers_in_tool_results_support_nothing():
    assert unsupported_numbers("seed 4", ["smoke-4"]) == ["4"]


def test_a_version_like_token_is_not_a_figure():
    assert unsupported_numbers("lovelaice 2.13.1", []) == []


def test_figures_keep_the_spelling_of_the_answer():
    assert [f.text for f in figures("22,1 and 45 %")] == ["22,1", "45 %"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_evaluate_checker.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'casus.evaluate'`.

- [ ] **Step 3: Implement**

Create `src/casus/evaluate/__init__.py`:

```python
"""Evaluate mode: fixed queries over a study, and the check on an answer's figures.

`queries` and `checker` import nothing from lovelaice; only `tools` and `agent`
wrap them for the model."""
```

Create `src/casus/evaluate/checker.py`:

```python
"""Every figure an answer states must come from a query the agent ran.

`unsupported_numbers` finds the numbers in an answer and looks for each one in
the text the tools returned during the session. A stated figure is supported
when some returned number, rounded to the precision the answer used, equals
it: "22" is supported by 22.0075, "22,1" by 22.13, "22.13" is not supported by
22.1. Nothing here imports lovelaice: the check is plain text against plain
text, and it knows nothing of the agent that produced the answer.

What counts as a figure, decided here and pinned by tests:

- Decimal points and decimal commas are both read. A single separator followed
  by exactly three digits ("1,234", "1.234") is ambiguous between a thousands
  separator and a decimal one, and a figure is supported if either reading is.
  Two different separators ("1.234,5", "1,234.5") read the last as decimal.
  A no-break space or a thin space between digit groups is a thousands
  separator; a plain space is not, because "day 3 100 units" is two figures.
- "45%" or "45 %" is supported by 45 or by 0.45, at the precision stated.
- The sign is not checked. Prose carries it in words ("fell by 15.8"), and the
  ledger returns each change with its sign.
- Not figures: digits inside a word or an identifier ("qwen3", "3rd", "2º",
  "smoke-4", "t0.02", a hex version), a dotted version ("2.13.1"), and the
  number of a list item at the start of a line ("1. ", "2) ").
- Years, day numbers and counts are figures like any other. Day numbers and
  run counts are almost always supported, because every series lists its
  turns; a year that no query returned came from the model's memory, and the
  room should see that.
"""

from __future__ import annotations

import dataclasses
import re
from decimal import Decimal

_LETTER = r"A-Za-zªµºÀ-ɏ_"
#: Group separators other than a plain space: "day 3 100 units" is two figures.
_GROUPS = "   "
#: A number not glued to a word: no letter, digit or separator before it, no
#: "word-" before it, and no letter or digit after it.
_NUMBER = re.compile(
    rf"(?<![{_LETTER}0-9.,])(?<![{_LETTER}0-9]-)"
    rf"(\d{{1,3}}(?:[{_GROUPS}]\d{{3}})+(?:[.,]\d+)?|\d+(?:[.,]\d+)*)"
    rf"(?![{_LETTER}0-9])(?![.,]\d)"
    rf"([ {_GROUPS}]?%)?"
)
#: "1. " or "2) " opening a line, possibly after a quote, heading or bullet mark.
_LIST_ITEM = re.compile(r"^[ \t>#*-]*(\d+)[.)][ \t]", re.MULTILINE)


@dataclasses.dataclass(frozen=True)
class Figure:
    text: str  # as written, for marking it in the answer
    readings: tuple[tuple[Decimal, int], ...]  # (value, decimals) per reading
    percent: bool


def _readings(token: str) -> tuple[tuple[Decimal, int], ...]:
    for space in _GROUPS:
        token = token.replace(space, "")
    seps = [c for c in token if c in ".,"]
    if not seps:
        return ((Decimal(token), 0),)
    if len(set(seps)) == 2:
        decimal_sep = seps[-1]
        thousands = "," if decimal_sep == "." else "."
        whole, frac = token.replace(thousands, "").split(decimal_sep)
        return ((Decimal(f"{whole}.{frac}"), len(frac)),)
    sep = seps[0]
    parts = token.split(sep)
    if len(parts) > 2:
        if all(len(p) == 3 for p in parts[1:]) and 1 <= len(parts[0]) <= 3:
            return ((Decimal("".join(parts)), 0),)
        return ()  # "1.2.3" is a version or a date, not a figure
    whole, frac = parts
    as_decimal = (Decimal(f"{whole}.{frac}"), len(frac))
    if len(frac) == 3 and 1 <= len(whole) <= 3 and not whole.startswith("0"):
        return (as_decimal, (Decimal(whole + frac), 0))
    return (as_decimal,)


def figures(text: str) -> list[Figure]:
    """The figures in a text, in order, list-item numbers left out."""
    items = {m.start(1) for m in _LIST_ITEM.finditer(text)}
    out = []
    for m in _NUMBER.finditer(text):
        if m.start(1) in items:
            continue
        readings = _readings(m.group(1))
        if readings:
            out.append(Figure(m.group(1) + (m.group(2) or ""), readings, bool(m.group(2))))
    return out


def _supported(figure: Figure, returned: list[Decimal]) -> bool:
    for value, decimals in figure.readings:
        tolerance = Decimal(5) * Decimal(10) ** (-(decimals + 1))
        for r in returned:
            candidates = (r, r * 100) if figure.percent else (r,)
            if any(abs(c - value) <= tolerance for c in candidates):
                return True
    return False


def unsupported_numbers(answer: str, tool_results: list[str]) -> list[str]:
    """The figures in `answer` that no tool result supports, each once, in the
    order they first appear, spelled as the answer spells them."""
    returned = sorted(
        {abs(value) for text in tool_results for f in figures(text) for value, _ in f.readings}
    )
    out: list[str] = []
    for figure in figures(answer):
        if figure.text not in out and not _supported(figure, returned):
            out.append(figure.text)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_evaluate_checker.py -q`
Expected: PASS (31 tests).

- [ ] **Step 5: Break it on purpose**

In `_supported`, change the tolerance to `Decimal(0)`. Run `uv run pytest tests/test_evaluate_checker.py -q -k rounds_to_it`. Expected: FAIL ("22" no longer matches 22.0075). Revert.

- [ ] **Step 6: Commit**

```bash
git add src/casus/evaluate/__init__.py src/casus/evaluate/checker.py \
  tests/test_evaluate_checker.py
git commit -m "feat(evaluate): the check that every figure came from a query"
```

---

### Task 3: The fixed queries

**Files:**
- Create: `src/casus/evaluate/queries.py`
- Test: `tests/test_evaluate_queries.py`

**Interfaces:**
- Consumes: `Study`, `RunInfo` (Task 1); `unsupported_numbers` (Task 2, in a test).
- Produces: `series(study, quantity, holder)`, `finals(study, quantity, holder)`, `events(study, event_id=None)`, `ledger(study, ref, run)`, `choices(study, actor=None)` (master plan), and `runs(study)`, `read_scenario(study)`, `read_rules(study)`, `render(result) -> str`, `fmt(value) -> str`, `QueryError`. Every query returns a JSON-able dict with a `query` key.

A holder is an actor, a place or an entity id; the quantity is one of its resources or attributes. `series` and `finals` print the value's `ref` (`actor.BLUE.stamina`, `place.border.infra`, `entity.blue-1.strength`), which is what `ledger` takes, and `ledger` takes a run id or its seed. A row of `series` is the state at the start of that turn; the last row is the state after the final turn, so the ledger's turn-N mutations turn row N into row N+1. `fmt` prints two decimals (four below one) and never exponent notation, because the checker reads the model's figures against this text.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_evaluate_queries.py`:

```python
"""The fixed queries, against a recorded smoke study. Every expected value is
read from the transcripts here, never from a query's own output."""

import json
import statistics
import subprocess
import sys

import pytest
import yaml
from evaluate_support import SEEDS, SMOKE, TURNS, record_study, records

from casus import studies
from casus.evaluate import queries
from casus.evaluate.checker import unsupported_numbers


@pytest.fixture(scope="module")
def study(tmp_path_factory):
    return record_study(tmp_path_factory.mktemp("runs"))


def _states(recs):
    return [r["state"] for r in recs if r["kind"] == "state"]


def test_list_runs_gives_each_runs_seed_status_and_standing_at_the_end(study):
    result = queries.runs(study)
    standing = yaml.safe_load((SMOKE / "scenario.yaml").read_text())["display"]["standing"]
    assert [r["seed"] for r in result["runs"]] == list(SEEDS)
    for row, (run_id, recs) in zip(result["runs"], records(study).items(), strict=True):
        last = _states(recs)[-1]
        assert row["id"] == run_id and row["status"] == "complete"
        assert row["turns_done"] == TURNS
        assert row["end"] == {
            a: {k: last["actors"][a]["resources"][k] for k in standing} for a in last["actors"]
        }


def test_series_is_the_state_value_turn_by_run(study):
    result = queries.series(study, "infra", "border")
    assert result["ref"] == "place.border.infra"
    for row, recs in zip(result["runs"], records(study).values(), strict=True):
        expected = [s["places"]["border"]["attrs"]["infra"] for s in _states(recs)]
        assert row["values"] == expected
    first = next(iter(records(study).values()))
    assert result["turns"] == [s["turn"] for s in _states(first)]


def test_series_starts_from_the_scenario_value(study):
    initial = yaml.safe_load((SMOKE / "scenario.yaml").read_text())["actors"]["BLUE"]
    result = queries.series(study, "stamina", "BLUE")
    assert {row["values"][0] for row in result["runs"]} == {initial["resources"]["stamina"]}


def test_series_of_an_entity_attribute(study):
    result = queries.series(study, "strength", "blue-1")
    assert result["ref"] == "entity.blue-1.strength"


def test_finals_are_the_last_state_with_min_median_and_max(study):
    result = queries.finals(study, "infra", "border")
    finals = [
        _states(recs)[-1]["places"]["border"]["attrs"]["infra"]
        for recs in records(study).values()
    ]
    assert [r["value"] for r in result["runs"]] == finals
    assert (result["min"], result["median"], result["max"]) == (
        min(finals),
        statistics.median(finals),
        max(finals),
    )
    assert result["spread"] == max(finals) - min(finals)
    assert result["n"] == len(SEEDS)


def test_a_run_cut_short_has_no_value_for_the_turns_it_did_not_reach(tmp_path):
    study = record_study(tmp_path)
    path = study.runs[0].path
    lines = path.read_text().splitlines()
    last_state = max(i for i, line in enumerate(lines) if '"kind": "state"' in line)
    path.write_text("\n".join(lines[:last_state]) + "\n")
    [study] = studies.list_studies(tmp_path)
    result = queries.series(study, "infra", "border")
    assert result["runs"][0]["values"][-1] is None
    assert queries.finals(study, "infra", "border")["runs"][0]["status"] == "incomplete"


def test_events_count_per_run_with_their_turns(study):
    result = queries.events(study)
    for row, recs in zip(result["runs"], records(study).values(), strict=True):
        turns = [
            r["turn"] for r in recs if r["kind"] == "event" and r["event"]["id"] == "raided"
        ]
        assert row["turns"]["raided"] == turns
        assert row["counts"]["raided"] == len(turns)
    assert result["totals"]["raided"] == sum(len(r["turns"]["raided"]) for r in result["runs"])


def test_events_of_an_id_nobody_recorded_is_zero_and_names_what_was(study):
    result = queries.events(study, "invaded")
    assert result["totals"] == {"invaded": 0}
    assert "raided" in queries.render(result)


def test_the_ledger_lists_every_mutation_of_one_value(study):
    run = study.runs[0]
    result = queries.ledger(study, "place.border.infra", run.id)
    recs = records(study)[run.id]
    expected = [r for r in recs if r["kind"] == "mutation" and r["ref"] == "place.border.infra"]
    assert [(m["turn"], m["rule"], m["before"], m["after"]) for m in result["mutations"]] == [
        (r["turn"], r["rule"], r["before"], r["after"]) for r in expected
    ]
    assert result["raised_by"] == []
    assert result["lowered_by"] == sorted({r["rule"] for r in expected})


def test_the_ledger_takes_a_seed_for_the_run(study):
    by_seed = queries.ledger(study, "actor.BLUE.stamina", str(study.runs[1].seed))
    assert by_seed["run"] == study.runs[1].id


def test_a_value_no_rule_touched_has_an_empty_ledger(study):
    result = queries.ledger(study, "place.b-home.infra", study.runs[0].id)
    assert result["mutations"] == [] and result["rules"] == []


def test_a_spawn_is_in_the_ledger_without_a_change(study):
    """Three raids at full intensity take the border below the militia line, so
    the recovery rule spawns one: an entity mutation with no before."""
    recs = records(study)[study.runs[0].id]
    spawned = [r for r in recs if r["kind"] == "mutation" and r["before"] is None]
    assert spawned, "the fixture no longer spawns a militia; raise the raid intensity"
    result = queries.ledger(study, spawned[0]["ref"], study.runs[0].id)
    assert result["mutations"][0]["change"] is None
    assert "absent" in queries.render(result)


def test_choices_count_the_declared_action_types(study):
    result = queries.choices(study)
    for row, recs in zip(result["runs"], records(study).values(), strict=True):
        actions = [r for r in recs if r["kind"] == "action"]
        for actor in {r["actor"] for r in actions}:
            types = [r["action"]["type"] for r in actions if r["actor"] == actor]
            assert row["counts"][actor] == {t: types.count(t) for t in set(types)}
        assert len(row["per_turn"]) == len({(r["turn"], r["actor"]) for r in actions})


def test_choices_of_one_actor(study):
    assert set(queries.choices(study, "RED")["totals"]) == {"RED"}


def test_read_scenario_and_read_rules_are_the_versions_own(study):
    header = records(study)[study.runs[0].id][0]
    assert yaml.safe_load(queries.read_scenario(study)["yaml"]) == header["scenario"]
    assert queries.read_rules(study)["source"] == header["rules_source"]


@pytest.mark.parametrize(
    "call, message",
    [
        (lambda s: queries.series(s, "infra", "atlantis"), "places: b-home, border, r-home"),
        (lambda s: queries.series(s, "morale", "BLUE"), "stamina, supplies"),
        (lambda s: queries.ledger(s, "border.infra", s.runs[0].id), "place.<id>.<attribute>"),
        (lambda s: queries.ledger(s, "place.border.infra", "99"), "(seed 1)"),
        (lambda s: queries.ledger(s, "place.border.morale", "1"), "no value"),
        (lambda s: queries.choices(s, "GREEN"), "BLUE, RED"),
    ],
)
def test_a_wrong_name_says_what_the_study_has(study, call, message):
    with pytest.raises(queries.QueryError) as caught:
        call(study)
    assert message in str(caught.value)


def test_every_result_is_plain_json_and_renders(study):
    results = [
        queries.runs(study),
        queries.series(study, "infra", "border"),
        queries.finals(study, "infra", "border"),
        queries.events(study),
        queries.ledger(study, "place.border.infra", study.runs[0].id),
        queries.choices(study),
        queries.read_scenario(study),
        queries.read_rules(study),
    ]
    for result in results:
        assert json.loads(json.dumps(result)) == result
        assert queries.render(result).strip()


def test_the_rendered_series_carries_every_value_the_model_may_cite(study):
    result = queries.series(study, "infra", "border")
    cited = " ".join(queries.fmt(v) for row in result["runs"] for v in row["values"])
    assert unsupported_numbers(cited, [queries.render(result)]) == []


def test_queries_checker_and_the_server_import_without_lovelaice():
    """Only the agent modules import lovelaice: the queries, the check and the
    server stay plain code the study screen, its chart and its batches use."""
    code = (
        "import sys; sys.modules['lovelaice'] = None\n"
        "import casus.evaluate.queries, casus.evaluate.checker\n"
        "import casus.server.app\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
```

The expected values are read from the transcripts in the test, never from a query's output. Two come from the scenario file (the initial stamina, the `standing` list), so a change to the smoke scenario moves both sides.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_evaluate_queries.py -q`
Expected: FAIL with `ImportError: cannot import name 'queries' from 'casus.evaluate'`.

- [ ] **Step 3: Implement**

Create `src/casus/evaluate/queries.py`:

```python
"""The fixed queries the evaluate agent answers from.

Each query reads a study's transcripts and returns a plain JSON-able dict with a
`query` key; `render` turns any of them into the compact text the model reads.
The model runs no code of its own: a question these cannot answer is a gap in
the queries, and the fix is a new query with a test.

Values come from `state` records (the world at the start of each turn, and
after the last one) and `mutation` records (the ledger). No lovelaice import
here: the study screen and its chart read these without the agent.
"""

from __future__ import annotations

import functools
import json
import pathlib
import statistics
from typing import Any

import yaml

from ..studies import RunInfo, Study

SCOPES = ("actor", "place", "entity")


class QueryError(ValueError):
    """The query named something the study does not have. The message says what
    it does have, so the agent can correct itself."""


# --- reading ------------------------------------------------------------------


@functools.lru_cache(maxsize=256)
def _read(path: str, mtime_ns: int, size: int) -> tuple[dict, ...]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                break  # the half-written last line of a run still playing
    return tuple(out)


def _records(info: RunInfo) -> tuple[dict, ...]:
    stat = pathlib.Path(info.path).stat()
    return _read(str(info.path), stat.st_mtime_ns, stat.st_size)


def _states(info: RunInfo) -> list[dict]:
    return [r["state"] for r in _records(info) if r["kind"] == "state"]


def _header(study: Study) -> dict:
    return _records(study.runs[0])[0]


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _pool(state: dict, holder: str) -> tuple[str, dict] | None:
    """The scope of a holder in one state, and the values it holds there."""
    if holder in state["actors"]:
        return "actor", state["actors"][holder]["resources"]
    if holder in state["places"]:
        return "place", state["places"][holder]["attrs"]
    for entity in state["entities"]:
        if entity["id"] == holder:
            return "entity", {**entity["attrs"], "place": entity["place"]}
    return None


def _value(state: dict, quantity: str, holder: str) -> Any:
    found = _pool(state, holder)
    return None if found is None else found[1].get(quantity)


def _holders(study: Study) -> dict[str, tuple[str, set[str]]]:
    """Every holder in any state of any run, with its scope and quantities.
    An entity spawned mid-run is here; so is one removed before the end."""
    out: dict[str, tuple[str, set[str]]] = {}
    for info in study.runs:
        for state in _states(info):
            ids = [*state["actors"], *state["places"], *(e["id"] for e in state["entities"])]
            for ident in ids:
                scope, pool = _pool(state, ident)
                out.setdefault(ident, (scope, set()))[1].update(pool)
    return out


def _scope(study: Study, quantity: str, holder: str) -> str:
    holders = _holders(study)
    if holder not in holders:
        by_scope: dict[str, list[str]] = {}
        for ident, (scope, _) in sorted(holders.items()):
            by_scope.setdefault(scope, []).append(ident)
        known = "; ".join(f"{s}s: {', '.join(ids)}" for s, ids in by_scope.items())
        raise QueryError(f"no actor, place or entity '{holder}'. {known}")
    scope, quantities = holders[holder]
    if quantity not in quantities:
        raise QueryError(
            f"'{holder}' has no '{quantity}'; it has {', '.join(sorted(quantities))}"
        )
    return scope


def _run(study: Study, run: str) -> RunInfo:
    for info in study.runs:
        if run in (info.id, str(info.seed), f"seed {info.seed}"):
            return info
    ids = ", ".join(f"{i.id} (seed {i.seed})" for i in study.runs)
    raise QueryError(f"no run '{run}' in this study; its runs are {ids}")


# --- the queries ----------------------------------------------------------------


def runs(study: Study) -> dict:
    """Each run: id, seed, turns completed, status, its error if it failed, and
    the displayed quantities (`display.standing`, else every resource) at the end."""
    scenario = _header(study)["scenario"]
    display = scenario.get("display") or {}
    standing = list(display.get("standing") or scenario.get("resources") or ())
    rows = []
    for info in study.runs:
        states = _states(info)
        last = states[-1] if states else {"actors": {}}
        error = next((r.get("error") for r in _records(info) if r["kind"] == "error"), None)
        end = {
            actor: {k: last["actors"][actor]["resources"].get(k) for k in standing}
            for actor in sorted(last["actors"])
        }
        rows.append(
            {
                "id": info.id,
                "seed": info.seed,
                "status": info.status,
                "error": error,
                "turns_done": info.turns_done,
                "turns_planned": info.turns_planned,
                "end": end,
            }
        )
    return {
        "query": "list_runs",
        "scenario": study.scenario,
        "version": study.version,
        "standing": standing,
        "runs": rows,
    }


def series(study: Study, quantity: str, holder: str) -> dict:
    """One quantity of one actor, place or entity: turn by run. A run that did
    not reach a turn, or an entity absent that turn, has None there."""
    scope = _scope(study, quantity, holder)
    turns = sorted({s["turn"] for info in study.runs for s in _states(info)})
    rows = []
    for info in study.runs:
        by_turn = {s["turn"]: _value(s, quantity, holder) for s in _states(info)}
        values = [by_turn.get(t) for t in turns]
        rows.append({"id": info.id, "seed": info.seed, "status": info.status, "values": values})
    return {
        "query": "series",
        "quantity": quantity,
        "holder": holder,
        "ref": f"{scope}.{holder}.{quantity}",
        "turns": turns,
        "runs": rows,
    }


def finals(study: Study, quantity: str, holder: str) -> dict:
    """The value in each run's last recorded state, with min, median, max, and
    the spread between min and max."""
    scope = _scope(study, quantity, holder)
    rows = []
    for info in study.runs:
        states = _states(info)
        last = states[-1] if states else None
        rows.append(
            {
                "id": info.id,
                "seed": info.seed,
                "status": info.status,
                "turn": last["turn"] if last else None,
                "value": _value(last, quantity, holder) if last else None,
            }
        )
    numbers = [r["value"] for r in rows if _number(r["value"])]
    stats: dict[str, Any] = {"n": len(numbers)}
    if numbers:
        low, high = min(numbers), max(numbers)
        stats |= {"min": low, "median": statistics.median(numbers), "max": high}
        stats["spread"] = high - low
    else:
        stats |= {"min": None, "median": None, "max": None, "spread": None}
    return {
        "query": "finals",
        "quantity": quantity,
        "holder": holder,
        "ref": f"{scope}.{holder}.{quantity}",
        "runs": rows,
        **stats,
    }


def events(study: Study, event_id: str | None = None) -> dict:
    """How many times each event happened in each run, and on which turns."""
    rows, totals, seen = [], {}, set()
    for info in study.runs:
        turns: dict[str, list[int]] = {}
        for r in _records(info):
            if r["kind"] != "event":
                continue
            seen.add(r["event"]["id"])
            if event_id is None or r["event"]["id"] == event_id:
                turns.setdefault(r["event"]["id"], []).append(r["turn"])
        counts = {k: len(v) for k, v in sorted(turns.items())}
        rows.append(
            {
                "id": info.id,
                "seed": info.seed,
                "counts": counts,
                "turns": dict(sorted(turns.items())),
            }
        )
        for k, n in counts.items():
            totals[k] = totals.get(k, 0) + n
    if event_id is not None:
        totals.setdefault(event_id, 0)
    return {
        "query": "events",
        "event": event_id,
        "runs": rows,
        "totals": dict(sorted(totals.items())),
        "seen": sorted(seen),
    }


def ledger(study: Study, ref: str, run: str) -> dict:
    """Every mutation of one value in one run: turn, phase, rule, before, after,
    and the change when both are numbers. `run` is a run id or its seed."""
    info = _run(study, run)
    parts = ref.split(".", 2)
    if len(parts) < 2 or parts[0] not in SCOPES:
        raise QueryError(
            "a ref is actor.<id>.<resource>, place.<id>.<attribute> or "
            "entity.<id>[.<attribute>], as series and finals print it"
        )
    rows = []
    for r in _records(info):
        if r["kind"] != "mutation" or r["ref"] != ref:
            continue
        numeric = _number(r["before"]) and _number(r["after"])
        rows.append(
            {
                "turn": r["turn"],
                "phase": r["phase"],
                "rule": r["rule"],
                "before": r["before"],
                "after": r["after"],
                "change": r["after"] - r["before"] if numeric else None,
            }
        )
    if not rows:
        holders = _holders(study)
        scope, quantities = holders.get(parts[1], (None, set()))
        if scope != parts[0] or (len(parts) == 3 and parts[2] not in quantities):
            raise QueryError(f"no value '{ref}' in this study")
    changed = [m for m in rows if m["change"] is not None]
    return {
        "query": "ledger",
        "ref": ref,
        "run": info.id,
        "seed": info.seed,
        "mutations": rows,
        "rules": sorted({m["rule"] for m in rows}),
        "raised_by": sorted({m["rule"] for m in changed if m["change"] > 0}),
        "lowered_by": sorted({m["rule"] for m in changed if m["change"] < 0}),
    }


def _describe(action: dict) -> str:
    text = action["type"]
    if action.get("place"):
        text += f" {action['place']}"
    if action.get("target"):
        text += f" → {action['target']}"
    if action.get("entities"):
        text += f" [{', '.join(action['entities'])}]"
    if int(action.get("intensity", 1)) != 1:
        text += f" ×{action['intensity']}"
    return text


def choices(study: Study, actor: str | None = None) -> dict:
    """The action types each actor declared, counted per run and listed per turn."""
    actors = sorted(_header(study)["scenario"]["actors"])
    if actor is not None and actor not in actors:
        raise QueryError(f"no actor '{actor}'; the actors are {', '.join(actors)}")
    rows: list[dict] = []
    totals: dict[str, dict[str, int]] = {}
    for info in study.runs:
        counts: dict[str, dict[str, int]] = {}
        per_turn: list[dict] = []
        for r in _records(info):
            if r["kind"] != "action" or actor not in (None, r["actor"]):
                continue
            kind = r["action"]["type"]
            for table in (counts, totals):
                mine = table.setdefault(r["actor"], {})
                mine[kind] = mine.get(kind, 0) + 1
            key = (r["turn"], r["actor"])
            if not per_turn or (per_turn[-1]["turn"], per_turn[-1]["actor"]) != key:
                per_turn.append({"turn": r["turn"], "actor": r["actor"], "actions": []})
            per_turn[-1]["actions"].append(_describe(r["action"]))
        rows.append({"id": info.id, "seed": info.seed, "counts": counts, "per_turn": per_turn})
    return {"query": "choices", "actor": actor, "runs": rows, "totals": totals}


def read_scenario(study: Study) -> dict:
    """The version's scenario data as YAML. The transcript carries the data, not
    the file, so comments in the original are not here."""
    data = _header(study)["scenario"]
    return {
        "query": "read_scenario",
        "yaml": yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=96),
    }


def read_rules(study: Study) -> dict:
    """The version's rules source, exactly as the runs executed it."""
    return {"query": "read_rules", "source": _header(study)["rules_source"]}


# --- text for the model -----------------------------------------------------------


def fmt(value: Any) -> str:
    """A value as the model reads it: an integer when it is one, else two
    decimals (four below one), trailing zeros dropped. Never exponent notation,
    which the checker would not read as a figure."""
    if value is None:
        return "–"
    if not _number(value):
        return str(value)
    if float(value).is_integer():
        return str(int(value))
    text = f"{value:.2f}" if abs(value) >= 1 else f"{value:.4f}"
    return text.rstrip("0").rstrip(".")


def _names(items) -> str:
    return ", ".join(items) or "none"


def _counted(counts: dict[str, dict[str, int]]) -> str:
    return "; ".join(
        f"{a} " + ", ".join(f"{t} {n}" for t, n in sorted(c.items()))
        for a, c in sorted(counts.items())
    )


def _render_runs(r: dict) -> list[str]:
    lines = [f"study {r['scenario']} version {r['version']}: {len(r['runs'])} runs"]
    for run in r["runs"]:
        end = "; ".join(
            f"{actor} " + ", ".join(f"{k} {fmt(v)}" for k, v in values.items())
            for actor, values in run["end"].items()
        )
        line = (
            f"seed {run['seed']} · {run['id']} · {run['turns_done']}/{run['turns_planned']}"
            f" turns · {run['status']} · end: {end}"
        )
        lines.append(line + (f" · error: {run['error']}" if run["error"] else ""))
    return lines


def _render_series(r: dict) -> list[str]:
    head = f"series: {r['quantity']} of {r['holder']} (ref {r['ref']}), {len(r['runs'])} runs"
    note = "value at the start of each turn; the last row is after the final turn; – is none"
    columns = " | ".join(f"seed {run['seed']}" for run in r["runs"])
    rows = [
        f"{turn} | " + " | ".join(fmt(run["values"][i]) for run in r["runs"])
        for i, turn in enumerate(r["turns"])
    ]
    return [head, note, f"turn | {columns}", *rows]


def _render_finals(r: dict) -> list[str]:
    lines = [
        f"finals: {r['quantity']} of {r['holder']} (ref {r['ref']}), "
        f"the last recorded state of each of {len(r['runs'])} runs"
    ]
    for run in r["runs"]:
        where = f"{run['id']}, {run['status']}, turn {run['turn']}"
        lines.append(f"seed {run['seed']} ({where}): {fmt(run['value'])}")
    lines.append(
        f"min {fmt(r['min'])} · median {fmt(r['median'])} · max {fmt(r['max'])}"
        f" · spread {fmt(r['spread'])} · over {r['n']} runs with a value"
    )
    return lines


def _render_events(r: dict) -> list[str]:
    lines = [f"{'event ' + r['event'] if r['event'] else 'events'} in {len(r['runs'])} runs"]
    for event_id, total in r["totals"].items():
        lines.append(f"{event_id}: {total} in total")
        for run in r["runs"]:
            turns = run["turns"].get(event_id, [])
            on = f" (turns {', '.join(map(str, turns))})" if turns else ""
            lines.append(f"  seed {run['seed']}: {len(turns)}{on}")
    if not r["totals"]:
        lines.append("no events recorded")
    if r["event"] and r["event"] not in r["seen"]:
        lines.append(f"events recorded in this study: {_names(r['seen'])}")
    return lines


def _render_ledger(r: dict) -> list[str]:
    n = len(r["mutations"])
    lines = [f"ledger: {r['ref']} in run {r['run']} (seed {r['seed']}): {n} mutations"]
    for m in r["mutations"]:
        before = "absent" if m["before"] is None else fmt(m["before"])
        after = "removed" if m["after"] is None else fmt(m["after"])
        change = f" (change {fmt(m['change'])})" if m["change"] is not None else ""
        lines.append(f"turn {m['turn']} {m['phase']} {m['rule']}: {before} → {after}{change}")
    lines.append(
        f"rules that changed it: {_names(r['rules'])}; raised it: {_names(r['raised_by'])};"
        f" lowered it: {_names(r['lowered_by'])}"
    )
    return lines


def _render_choices(r: dict) -> list[str]:
    lines = [f"choices in {len(r['runs'])} runs", f"totals: {_counted(r['totals'])}"]
    for run in r["runs"]:
        lines.append(f"seed {run['seed']}: {_counted(run['counts'])}")
        turns: dict[int, list[str]] = {}
        for entry in run["per_turn"]:
            turns.setdefault(entry["turn"], []).append(
                f"{entry['actor']} {', '.join(entry['actions'])}"
            )
        lines += [f"  turn {t}: {'; '.join(parts)}" for t, parts in turns.items()]
    return lines


_RENDER = {
    "list_runs": _render_runs,
    "series": _render_series,
    "finals": _render_finals,
    "events": _render_events,
    "ledger": _render_ledger,
    "choices": _render_choices,
    "read_scenario": lambda r: [r["yaml"]],
    "read_rules": lambda r: [r["source"]],
}


def render(result: dict) -> str:
    """The compact text of any query result, for the model."""
    return "\n".join(_RENDER[result["query"]](result))
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_evaluate_queries.py -q`
Expected: PASS (24 tests).

- [ ] **Step 5: Commit**

```bash
git add src/casus/evaluate/queries.py tests/test_evaluate_queries.py
git commit -m "feat(evaluate): the fixed queries over a study's transcripts"
```

---

### Task 4: Batches

**Files:**
- Modify: `src/casus/server/runs.py`
- Modify: `tests/evaluate_support.py`
- Test: `tests/test_evaluate_batches.py`

**Interfaces:**
- Consumes: slice 3's `RunManager` internals named above; `helpers.LiveEngine` (slice 3).
- Produces: `async RunManager.start_batch(scenario_dir, *, n, first_seed, turns, concurrency) -> list[str]` (master plan); `batch_plan(scenario, *, n, turns, first_seed) -> dict` with `runs`, `turns`, `actors`, `first_seed`, `last_seed`, `calls`. In `tests/evaluate_support.py`: `Gauge(fail_first=0)` with `.factory(model)`, `.peak`, `.calls`.

`start_batch` reserves every id before any run starts, through slice 3's `_reserve`, so seed 1 of a new version gets `smoke-1-2.jsonl` beside the old version's `smoke-1.jsonl` instead of overwriting it, and every batch run can be followed like a live one. Each run waits on a semaphore of `concurrency` before its engines are built. Slice 3's `_play` records any failure in the transcript and finishes the run, so one failure does not reach `gather` or the other runs. `calls` counts one narrator call per turn; a turn with no event to report makes none, so it is a ceiling, and the screen says "at most".

- [ ] **Step 1: Extend the test support**

In `tests/evaluate_support.py`, add `import asyncio` to the imports, change `from helpers import RAIDING, FakeEngine` to `from helpers import RAIDING, FakeEngine, LiveEngine`, and append:

```python
class Gauge:
    """An engine factory whose engines count the model calls in flight across
    every run. The first `fail_first` calls raise, as a dead endpoint does."""

    def __init__(self, fail_first: int = 0):
        self.now = self.peak = self.calls = 0
        self.fail_first = fail_first

    def factory(self, model: str) -> LiveEngine:
        gauge = self

        class Counted(LiveEngine):
            async def create(self, context, schema, *instructions):
                gauge.calls += 1
                if gauge.calls <= gauge.fail_first:
                    raise RuntimeError("the endpoint refused")
                gauge.now += 1
                gauge.peak = max(gauge.peak, gauge.now)
                try:
                    await asyncio.sleep(0.01)
                    return await super().create(context, schema, *instructions)
                finally:
                    gauge.now -= 1

        return Counted()
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_evaluate_batches.py`:

```python
"""Batches: N seeds of a scenario's current version, a few at a time."""

import asyncio
import json

import pytest
import yaml
from evaluate_support import SMOKE, Gauge

from casus import studies
from casus.scenario import Scenario, ScenarioError
from casus.server.runs import RunManager, batch_plan


def _batch(runs_dir, gauge, scenario_dir=SMOKE, **kw):
    async def go():
        manager = RunManager(runs_dir, engine_factory=gauge.factory)
        ids = await manager.start_batch(scenario_dir, **kw)
        await asyncio.gather(*(manager._runs[i].task for i in ids))
        return ids

    return asyncio.run(go())


def _smoke() -> dict:
    return yaml.safe_load((SMOKE / "scenario.yaml").read_text())


def test_a_batch_records_n_runs_of_the_current_version(tmp_path):
    ids = _batch(tmp_path, Gauge(), n=4, first_seed=7, turns=1, concurrency=2)
    [study] = studies.list_studies(tmp_path)
    assert [r.id for r in study.runs] == ids
    assert [r.seed for r in study.runs] == [7, 8, 9, 10]
    assert {r.status for r in study.runs} == {"complete"}
    scenario = Scenario.load(SMOKE)
    current = {"scenario": scenario.data, "rules_source": scenario.rules_source}
    assert study.version == studies.version_of(current)


@pytest.mark.parametrize("concurrency", [1, 2, 3])
def test_the_concurrency_limit_holds(tmp_path, concurrency):
    gauge = Gauge()
    _batch(tmp_path, gauge, n=5, first_seed=1, turns=2, concurrency=concurrency)
    # Each run asks every actor at once, so a limit of c runs is c × actors calls.
    assert gauge.peak == concurrency * len(_smoke()["actors"])


def test_a_failing_run_is_recorded_and_the_batch_goes_on(tmp_path):
    _batch(tmp_path, Gauge(fail_first=1), n=3, first_seed=1, turns=1, concurrency=1)
    [study] = studies.list_studies(tmp_path)
    assert [r.status for r in study.runs] == ["failed", "complete", "complete"]
    last = json.loads(study.runs[0].path.read_text().splitlines()[-1])
    assert last["kind"] == "error" and "the endpoint refused" in last["error"]


def test_a_seed_already_on_disk_gets_its_own_file(tmp_path):
    """Seed 1 of a new version must not overwrite seed 1 of an old one."""
    first = _batch(tmp_path, Gauge(), n=1, first_seed=1, turns=1, concurrency=1)
    again = _batch(tmp_path, Gauge(), n=1, first_seed=1, turns=1, concurrency=1)
    assert first != again
    assert len(studies.list_runs(tmp_path)) == 2


def test_a_batch_of_a_scenario_that_does_not_load_reserves_nothing(tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "scenario.yaml").write_text("name: broken\n")
    with pytest.raises(ScenarioError):
        _batch(tmp_path / "runs", Gauge(), broken, n=2, first_seed=1, turns=1, concurrency=1)
    assert not (tmp_path / "runs").exists()


def test_the_plan_counts_one_call_per_actor_per_turn_plus_the_narrator():
    scenario = Scenario.load(SMOKE)
    plan = batch_plan(scenario, n=10, turns=None, first_seed=4)
    turns, actors = _smoke()["turns"], len(_smoke()["actors"])
    assert plan["calls"] == 10 * turns * actors + 10 * turns
    assert (plan["first_seed"], plan["last_seed"]) == (4, 13)
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_evaluate_batches.py -q`
Expected: FAIL with `ImportError: cannot import name 'batch_plan' from 'casus.server.runs'`.

- [ ] **Step 4: Implement**

In `src/casus/server/runs.py`, add these two methods to `RunManager`, just before `_play`:

```python
    async def start_batch(
        self, scenario_dir, *, n: int, first_seed: int, turns: int | None, concurrency: int
    ) -> list[str]:
        """Start `n` runs of the scenario as it is now, seeds `first_seed` onwards,
        and return their ids at once. At most `concurrency` play at the same time;
        the rest wait their turn. Every id is reserved before any run starts, so
        each run can be followed like any other, and a run that fails ends its
        own transcript with an error record without stopping the others.

        Raises `ScenarioError` before reserving anything when the scenario does
        not load."""
        scenario = await asyncio.to_thread(Scenario.load, scenario_dir)
        gate = asyncio.Semaphore(max(1, concurrency))
        ids = []
        for seed in range(first_seed, first_seed + n):
            path = self._reserve(scenario.name, seed)
            run = _Run()
            self._runs[path.stem] = run
            run.task = asyncio.create_task(self._queued(gate, run, scenario, path, seed, turns))
            ids.append(path.stem)
        return ids

    async def _queued(self, gate, run, scenario, path, seed, turns) -> None:
        async with gate:
            try:
                engines = {a: self.engine_factory(scenario.model(a)) for a in scenario.actors}
                first = next(iter(scenario.actors))
                narrator_model = scenario.narrator_model() or scenario.model(first)
                narrator = self.engine_factory(narrator_model)
            except Exception:
                log.exception("run %s could not build its engines", path.stem)
                await run.finish()
                return
            await self._play(run, scenario, path, seed, turns, engines, narrator)
```

and append at the end of the module:

```python
def batch_plan(scenario: Scenario, *, n: int, turns: int | None, first_seed: int) -> dict:
    """What a batch will cost before it starts: one call per actor per turn,
    plus at most one narrator call per turn. A turn with nothing to report makes
    no narrator call, so `calls` is a ceiling."""
    turns = turns if turns is not None else scenario.turns
    actors = len(scenario.actors)
    return {
        "runs": n,
        "turns": turns,
        "actors": actors,
        "first_seed": first_seed,
        "last_seed": first_seed + n - 1,
        "calls": n * turns * (actors + 1),
    }
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_evaluate_batches.py -q`
Expected: PASS (8 tests).

- [ ] **Step 6: Break it on purpose**

Replace `asyncio.Semaphore(max(1, concurrency))` with `asyncio.Semaphore(99)`. Run `uv run pytest tests/test_evaluate_batches.py -q -k concurrency_limit`. Expected: FAIL for concurrency 1, 2 and 3 (the peak is five runs' worth of calls). Revert.

- [ ] **Step 7: Commit**

```bash
git add src/casus/server/runs.py tests/evaluate_support.py tests/test_evaluate_batches.py
git commit -m "feat(runs): batches of seeds, a few at a time, each followable"
```

---

### Task 5: The study endpoints

**Files:**
- Create: `src/casus/server/study.py`
- Modify: `src/casus/server/app.py`
- Test: `tests/test_server.py`, `tests/test_evaluate_queries.py`

**Interfaces:**
- Consumes: `list_studies`, `version_of` (Task 1); `queries.series`, `QueryError` (Task 3); `start_batch`, `batch_plan` (Task 4); `scenario_dirs` (slice 1); `Settings.load` (slice 5).
- Produces: `casus.server.study.router(*, runs_dir, dirs, manager, settings=None) -> APIRouter`, and over HTTP under `/api/studies`:
  - `GET ""` → `[{scenario, version, runs, current, date}]`: `current` says whether the version is the scenario directory's version now; `date` is the newest run's file date.
  - `GET /{scenario}/{version}/series?quantity=&holder=` → `queries.series`; 404 for an unknown study, 422 with the query's message for a wrong name.
  - `GET /{scenario}/plan?n=10&turns=` → `batch_plan(...)` plus `version`, from the seed after the highest of the current version.
  - `POST /{scenario}/runs` with `{n: 1..100 = 10, turns: int | null}` → `{ids}`; 404 when no scenario directory has that name, 422 when it does not validate.

`{scenario}` is the scenario's name as the study carries it (from the transcript), not a directory name: an old version's study must keep its name whatever the directory is called now. The router finds the directory whose `scenario.yaml` has that name.

- [ ] **Step 1: Write the failing tests**

In `tests/test_server.py`, add to the imports:

```python
import time

from evaluate_support import Gauge, record_study

from casus import studies
from casus.server.runs import RunManager
from casus.settings import Settings
```

(merge with the file's existing imports; `pathlib`, `pytest`, `TestClient`, `create_app` and `SCENARIOS` are already there) and append:

```python
# --- studies (slice 7) -------------------------------------------------------------


@pytest.fixture
def study_runs(tmp_path) -> pathlib.Path:
    runs = tmp_path / "study-runs"
    runs.mkdir()
    record_study(runs, seeds=(1, 2))
    return runs


@pytest.fixture
def study_client(study_runs, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    app = create_app(
        scenarios_dir=SCENARIOS,
        runs_dir=study_runs,
        settings=Settings.load(path=tmp_path / "absent.toml", env={}),
        run_manager=RunManager(study_runs, engine_factory=Gauge().factory),
    )
    with TestClient(app) as client:  # one event loop for the test, so batches finish
        yield client


def _study(runs):
    [study] = studies.list_studies(runs)
    return study


def test_studies_are_listed_with_their_runs_and_whether_they_are_current(
    study_client, study_runs
):
    [listed] = study_client.get("/api/studies").json()
    study = _study(study_runs)
    assert (listed["scenario"], listed["version"]) == (study.scenario, study.version)
    assert [r["id"] for r in listed["runs"]] == [r.id for r in study.runs]
    assert listed["current"] is True and listed["date"]


def test_a_study_of_older_rules_is_not_current(study_client, study_runs):
    rules = (SCENARIOS / "smoke" / "rules.py").read_text()
    changed = rules.replace("RAID_DAMAGE = 5.0", "RAID_DAMAGE = 6.0")
    record_study(study_runs, seeds=(9,), rules=changed)
    listed = study_client.get("/api/studies").json()
    assert sorted(s["current"] for s in listed) == [False, True]


def test_the_series_endpoint_serves_the_query(study_client, study_runs):
    study = _study(study_runs)
    url = f"/api/studies/smoke/{study.version}/series?quantity=infra&holder=border"
    body = study_client.get(url).json()
    assert body["ref"] == "place.border.infra" and len(body["runs"]) == len(study.runs)


def test_a_wrong_series_name_is_a_422_that_says_what_exists(study_client, study_runs):
    version = _study(study_runs).version
    response = study_client.get(f"/api/studies/smoke/{version}/series?quantity=infra&holder=x")
    assert response.status_code == 422 and "border" in response.json()["detail"]


def test_an_unknown_study_is_a_404(study_client):
    url = "/api/studies/smoke/000000000000/series?quantity=a&holder=b"
    assert study_client.get(url).status_code == 404


def test_the_plan_counts_calls_from_the_next_seed(study_client, study_runs):
    plan = study_client.get("/api/studies/smoke/plan?n=10&turns=2").json()
    assert plan["first_seed"] == max(r.seed for r in _study(study_runs).runs) + 1
    assert plan["runs"] == 10 and plan["calls"] == 10 * 2 * (plan["actors"] + 1)


def test_add_runs_starts_a_batch_after_the_highest_seed(study_client, study_runs):
    before = [r.seed for r in _study(study_runs).runs]
    ids = study_client.post("/api/studies/smoke/runs", json={"n": 3, "turns": 1}).json()["ids"]
    assert len(ids) == 3
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        study = _study(study_runs)
        if len(study.runs) == 5 and all(r.status == "complete" for r in study.runs):
            break
        time.sleep(0.05)
    top = max(before)
    assert [r.seed for r in _study(study_runs).runs] == [*before, top + 1, top + 2, top + 3]


def test_add_runs_for_an_unknown_scenario_is_a_404(study_client):
    assert study_client.post("/api/studies/nope/runs", json={"n": 1}).status_code == 404


def test_add_runs_refuses_a_batch_of_zero(study_client):
    assert study_client.post("/api/studies/smoke/runs", json={"n": 0}).status_code == 422
```

In `tests/test_evaluate_queries.py`, in `test_queries_checker_and_the_server_import_without_lovelaice`, change `"import casus.server.app\n"` to `"import casus.server.app, casus.server.study\n"`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_server.py tests/test_evaluate_queries.py -q`
Expected: FAIL: `/api/studies` is a 404 and `casus.server.study` does not exist.

- [ ] **Step 3: Implement**

Create `src/casus/server/study.py`:

```python
"""The study endpoints: studies by version, their series, batches, and the
evaluate agent's chat. Built like the design router (`server/design.py`): the
agent module is imported inside the chat endpoint only, so this file stays
free of lovelaice and the study screen never loads the agent."""

from __future__ import annotations

import asyncio
import datetime
import pathlib
from collections.abc import Callable
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import studies
from ..evaluate import queries
from ..scenario import Scenario, ScenarioError
from .runs import RunManager, batch_plan


class BatchIn(BaseModel):
    n: int = Field(10, ge=1, le=100)
    turns: int | None = Field(None, ge=1)


def _version(scenario: Scenario) -> str:
    return studies.version_of(
        {"scenario": scenario.data, "rules_source": scenario.rules_source}
    )


def router(
    *,
    runs_dir: pathlib.Path,
    dirs: Callable[[], list[pathlib.Path]],
    manager: RunManager,
    settings: Any = None,
) -> APIRouter:
    api = APIRouter(prefix="/api/studies")

    def current_settings():
        if settings is not None:
            return settings
        from ..settings import Settings

        return Settings.load()

    def find(scenario: str, version: str) -> studies.Study:
        for study in studies.list_studies(runs_dir):
            if (study.scenario, study.version) == (scenario, version):
                return study
        raise HTTPException(404, "no such study")

    def directory_of(name: str) -> pathlib.Path | None:
        """A study names its scenario by the name inside it; find its directory."""
        for directory in dirs():
            data = yaml.safe_load((directory / "scenario.yaml").read_text()) or {}
            if data.get("name") == name:
                return directory
        return None

    def version_now(name: str) -> str | None:
        directory = directory_of(name)
        if directory is None:
            return None
        try:
            return _version(Scenario.load(directory, validate=False))
        except ScenarioError:
            return None

    async def current(name: str) -> tuple[pathlib.Path, Scenario, int]:
        """The scenario's directory, its current version loaded and validated,
        and the seed a batch starts from: one past the highest in that version."""
        directory = directory_of(name)
        if directory is None:
            raise HTTPException(404, "no such scenario")
        try:
            scenario = await asyncio.to_thread(Scenario.load, directory)
        except ScenarioError as exc:
            raise HTTPException(422, str(exc)) from exc
        version = _version(scenario)
        seeds = [
            run.seed
            for study in studies.list_studies(runs_dir)
            if (study.scenario, study.version) == (name, version)
            for run in study.runs
        ]
        return directory, scenario, max(seeds, default=0) + 1

    @api.get("")
    def all_studies() -> list[dict]:
        found = studies.list_studies(runs_dir)
        now = {name: version_now(name) for name in {s.scenario for s in found}}
        out = []
        for study in found:
            stamp = max(run.path.stat().st_mtime for run in study.runs)
            out.append(
                {
                    **study.to_json(),
                    "current": now[study.scenario] == study.version,
                    "date": datetime.date.fromtimestamp(stamp).isoformat(),
                }
            )
        return out

    @api.get("/{scenario}/{version}/series")
    def series(scenario: str, version: str, quantity: str, holder: str) -> dict:
        try:
            return queries.series(find(scenario, version), quantity, holder)
        except queries.QueryError as exc:
            raise HTTPException(422, str(exc)) from exc

    @api.get("/{scenario}/plan")
    async def plan(scenario: str, n: int = 10, turns: int | None = None) -> dict:
        _, loaded, first = await current(scenario)
        return {
            **batch_plan(loaded, n=n, turns=turns, first_seed=first),
            "version": _version(loaded),
        }

    @api.post("/{scenario}/runs")
    async def add_runs(scenario: str, body: BatchIn) -> dict:
        directory, _, first = await current(scenario)
        try:
            ids = await manager.start_batch(
                directory,
                n=body.n,
                first_seed=first,
                turns=body.turns,
                concurrency=current_settings().run_concurrency,
            )
        except ScenarioError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"ids": ids}

    return api
```

In `src/casus/server/app.py`, add `from . import study as study_api` to the imports, and inside `create_app`, just before `return app`:

```python
    app.include_router(
        study_api.router(
            runs_dir=runs_dir,
            dirs=lambda: scenario_dirs(scenarios_dir),
            manager=manager,
            settings=settings,
        )
    )
```

`manager` is the local slice 3 creates from `run_manager or RunManager(runs_dir)`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_server.py tests/test_evaluate_queries.py -q`
Expected: PASS, the earlier slices' tests and the nine new ones.

- [ ] **Step 5: Commit**

```bash
git add src/casus/server/study.py src/casus/server/app.py tests/test_server.py \
  tests/test_evaluate_queries.py
git commit -m "feat(server): studies by version, their series, and batches"
```

---

### Task 6: The lovelaice dependency, the nine tools and the evaluate agent

**Files:**
- Modify (unless slice 6 already did): `pyproject.toml`, `uv.lock`
- Modify (if slice 6 added it): `tests/test_purity.py`
- Create: `src/casus/evaluate/tools.py`, `src/casus/evaluate/agent.py`
- Modify: `tests/evaluate_support.py`
- Test: `tests/test_evaluate_tools.py`, `tests/test_evaluate_agent.py`

**Interfaces:**
- Consumes: the queries and `QueryError` (Task 3); `unsupported_numbers` (Task 2); `Settings.agent_model`, `api_key`, `endpoint` (slice 5); `lingo.tools.tool`; lovelaice `Agent`, `AgentConfig`, `AgentTool`, `ToolResult`, `Session`, `ReActNative` and the events `AssistantMessageDelta`, `AssistantMessageFinalized`, `ToolExecutionStart`, `ToolExecutionEnd`.
- Produces: `TOOL_NAMES`, `REFUSED`, `build_tools(study) -> list[AgentTool]`; `SYSTEM_PROMPT`, `build_evaluate_agent(study, settings, session_dir) -> EvaluateAgent` with `.agent`, `async .turn(text, send) -> str` (the stop reason's value) and `.unsupported() -> list[str]`; `exchanges(messages) -> list[dict]`, `history(study, session_dir) -> list[dict]`, `session_path(study, session_dir)`. In `tests/evaluate_support.py`: `QUESTION`, `Analyst(invent=False)`.

This mirrors slice 6's Tasks 4 and 5. Tools return `ToolResult`s; a refusal has `is_error` and its text opens with `REFUSED`, because a saved chat keeps a tool's text but not its error flag. `turn` sends `delta`, `tool_start` and `tool_end`; the caller sends `done` with `unsupported()`. `exchanges` rebuilds question, tool calls, answer and the answer's unsupported figures from a session, checking each answer only against tool results that existed when it ended, so a reopened study shows the same marks the live answer had. The model is faked as slice 6 fakes it: `lovelaice.agent.agent._build_llm` is monkeypatched to return `Analyst`, a stand-in shaped like slice 6's `ScriptedLLM` (`model`, `_on_token`, `calls`, `async chat(messages, tools=None)`), which picks each call's arguments from the previous tool results.

- [ ] **Step 1: The dependency and the purity test**

If `pyproject.toml`'s `[project] dependencies` has no lovelaice entry (slice 6 adds the same line), add:

```toml
    "lovelaice>=2.13.1",
```

Run: `uv lock && uv sync && uv run python -c "import lovelaice; print(lovelaice.__file__)"`
Expected: a path inside `.venv`.

CI needs nothing new: its one job runs `uv sync --locked`, which installs lovelaice with everything else, so the agent tests below run there and cannot skip.

If `tests/test_purity.py` has slice 6's `test_only_the_design_agent_imports_lovelaice`, rename it `test_only_the_agents_import_lovelaice`, make its allowed set

```python
    allowed = {"design/tools.py", "design/agent.py", "evaluate/tools.py", "evaluate/agent.py"}
```

and its module-level check

```python
            assert name not in (
                "casus.design.tools", "casus.design.agent",
                "casus.evaluate.tools", "casus.evaluate.agent",
            ), f"{relative} imports {name} at module level"  # fmt: skip
```

If the test is not there yet, slice 6 adds the evaluate files when it lands (see "Contract changes needed").

- [ ] **Step 2: Extend the test support**

In `tests/evaluate_support.py`, add `import re` and `from lingo.llm import Message, ToolCall` to the imports, and append:

```python
QUESTION = "Why does the border's infrastructure never recover?"


class Analyst:
    """Stands in for lingo.LLM the way `design_support.ScriptedLLM` does, and
    works the "never recovers" question as the spec says a careful analyst
    would: list_runs, series, ledger, read_rules, show, then an answer. Each
    call's arguments are read from the previous tool results, so a query that
    stops printing what the next one needs breaks the session. With `invent`,
    the answer adds a difference it computed itself."""

    model = "scripted"

    def __init__(self, invent: bool = False):
        self.invent = invent
        self.calls: list[tuple[list, list | None]] = []
        self._on_token = None

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append((list(messages), tools))
        seen = [m.content for m in messages if m.role == "tool"]
        reply = self._next(seen)
        if self._on_token and reply.content:
            self._on_token(reply.content)
        return reply

    @staticmethod
    def _call(name: str, **arguments) -> Message:
        tool_call = ToolCall(id=f"c-{name}", name=name, arguments=arguments)
        return Message.assistant("", tool_calls=[tool_call], stop_reason="tool_calls")

    def _next(self, seen: list[str]) -> Message:
        if len(seen) == 0:
            return self._call("list_runs")
        seed = re.search(r"^seed (\d+) ·", seen[0], re.MULTILINE).group(1)
        if len(seen) == 1:
            return self._call("series", quantity="infra", holder="border")
        if len(seen) == 2:
            ref = re.search(r"\(ref (\S+)\)", seen[1]).group(1)
            return self._call("ledger", ref=ref, run=seed)
        if len(seen) == 3:
            return self._call("read_rules")
        if len(seen) == 4:
            return self._call("show", quantity="infra", holder="border")
        ledger = seen[2].splitlines()
        start = re.search(r": (\S+) →", ledger[1]).group(1)
        end = re.search(r"→ (\S+) \(", ledger[-2]).group(1)
        answer = (
            f"In seed {seed} the border's infrastructure went from {start} to {end}. "
            "The ledger shows only the raid rule changed it, and it only lowered it. "
            "The recovery rule raises it only on a day without a raid, "
            "and Blue raided every day."
        )
        if self.invent:
            answer += f" That is a fall of {float(start) - float(end):.1f} points."
        return Message.assistant(answer, stop_reason="stop")
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_evaluate_tools.py`:

```python
"""The evaluate agent's nine tools, against a recorded smoke study."""

import asyncio
import re

import pytest
from evaluate_support import record_study

from casus.evaluate.tools import TOOL_NAMES, build_tools


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    study = record_study(tmp_path_factory.mktemp("runs"))
    return {t.name: t for t in build_tools(study)}


def _run(tools, name, **args):
    result = asyncio.run(tools[name].inner.run(**args))
    return result.content[0]["text"], result.is_error


def test_there_are_exactly_the_specs_nine_tools(tools):
    assert tuple(tools) == TOOL_NAMES
    assert {name: set(t.inner.parameters()) for name, t in tools.items()} == {
        "list_runs": set(), "series": {"quantity", "holder"}, "finals": {"quantity", "holder"},
        "events": {"id"}, "ledger": {"ref", "run"}, "choices": {"actor"},
        "read_scenario": set(), "read_rules": set(), "show": {"quantity", "holder"},
    }  # fmt: skip


def test_a_query_answers_as_text(tools):
    text, error = _run(tools, "series", quantity="infra", holder="border")
    assert not error and "(ref place.border.infra)" in text


def test_optional_arguments_can_be_left_out(tools):
    text, error = _run(tools, "events")
    assert not error and "raided" in text


def test_a_wrong_name_is_a_refusal_that_says_what_exists(tools):
    text, error = _run(tools, "finals", quantity="infra", holder="atlantis")
    assert error and text.startswith("refused: ") and "places: b-home, border, r-home" in text


def test_show_returns_no_figure_and_refuses_what_the_chart_cannot_draw(tools):
    text, error = _run(tools, "show", quantity="infra", holder="border")
    assert not error and not re.search(r"\d", text)
    _, error = _run(tools, "show", quantity="morale", holder="BLUE")
    assert error
```

Create `tests/test_evaluate_agent.py`:

```python
"""The evaluate agent end to end with a scripted model, as the design agent is
tested: real tools over a recorded study, the browser's messages, and the check
on the answer's figures. No network."""

import asyncio
import re

from evaluate_support import QUESTION, Analyst, record_study

from casus.evaluate.agent import (
    SYSTEM_PROMPT,
    build_evaluate_agent,
    history,
    session_path,
)
from casus.evaluate.tools import TOOL_NAMES
from casus.settings import Settings


def _agent(tmp_path, llm, monkeypatch):
    monkeypatch.setattr("lovelaice.agent.agent._build_llm", lambda config: llm)
    runs = tmp_path / "runs"
    runs.mkdir(exist_ok=True)
    study = record_study(runs)
    settings = Settings.load(path=tmp_path / "absent.toml", env={})
    return study, build_evaluate_agent(study, settings, tmp_path / "sessions")


def _turn(evaluate, text=QUESTION):
    sent = []
    stop = asyncio.run(evaluate.turn(text, sent.append))
    return stop, sent


def _ends(sent):
    names = {m["id"]: m["name"] for m in sent if m["type"] == "tool_start"}
    return {names[m["id"]]: m for m in sent if m["type"] == "tool_end"}


def test_the_system_prompt_carries_the_rules_the_tools_cannot_enforce():
    for rule in (
        "never compute a number yourself", "Start with list_runs", "call show",
        "read its ledger", "read_rules", "by seed", "suggest adding runs",
    ):  # fmt: skip
        assert rule in SYSTEM_PROMPT


def test_the_agent_sees_its_nine_tools_and_no_path(tmp_path, monkeypatch):
    study, evaluate = _agent(tmp_path, Analyst(), monkeypatch)
    assert [t.name for t in evaluate.agent.harness.tools.all()] == list(TOOL_NAMES)
    assert str(tmp_path) not in evaluate.agent.harness.system_prompt
    assert study.version in evaluate.agent.harness.system_prompt


def test_the_never_recovers_question_reaches_the_ledger_and_the_rules(tmp_path, monkeypatch):
    _, evaluate = _agent(tmp_path, Analyst(), monkeypatch)
    stop, sent = _turn(evaluate)
    assert stop == "end_turn"
    called = [m["name"] for m in sent if m["type"] == "tool_start"]
    assert called.index("series") < called.index("ledger") < called.index("read_rules")
    ends = _ends(sent)
    assert all(m["ok"] for m in ends.values()), [m["result"] for m in ends.values()]
    assert "lowered it: raid" in ends["ledger"]["result"]
    assert "raised it: none" in ends["ledger"]["result"]
    assert "def recovery" in ends["read_rules"]["result"]


def test_an_answer_from_the_tools_has_no_unsupported_figures(tmp_path, monkeypatch):
    study, evaluate = _agent(tmp_path, Analyst(), monkeypatch)
    _, sent = _turn(evaluate)
    assert evaluate.unsupported() == []
    [exchange] = history(study, tmp_path / "sessions")
    assert "".join(m["text"] for m in sent if m["type"] == "delta") == exchange["answer"]


def test_a_figure_the_model_derived_is_unsupported(tmp_path, monkeypatch):
    _, evaluate = _agent(tmp_path, Analyst(invent=True), monkeypatch)
    _turn(evaluate)
    [derived] = evaluate.unsupported()
    assert re.fullmatch(r"\d+\.\d", derived)


def test_show_reaches_the_browser_as_a_tool_call(tmp_path, monkeypatch):
    _, evaluate = _agent(tmp_path, Analyst(), monkeypatch)
    _, sent = _turn(evaluate)
    [start] = [m for m in sent if m["type"] == "tool_start" and m["name"] == "show"]
    assert start["args"] == {"quantity": "infra", "holder": "border"}
    assert _ends(sent)["show"]["ok"]


def test_the_chat_persists_per_study_and_is_checked_again_when_read(tmp_path, monkeypatch):
    study, evaluate = _agent(tmp_path, Analyst(invent=True), monkeypatch)
    _turn(evaluate)
    path = session_path(study, tmp_path / "sessions")
    assert path.is_file() and path.parent == tmp_path / "sessions" / "studies"
    [exchange] = history(study, tmp_path / "sessions")
    assert exchange["question"] == QUESTION
    assert [t["name"] for t in exchange["tools"]][-1] == "show"
    assert exchange["unsupported"] == evaluate.unsupported()
    _, again = _agent(tmp_path, Analyst(), monkeypatch)
    history_in_prompt = again.agent.messages_for_llm()
    assert any(m.role == "user" and m.content == QUESTION for m in history_in_prompt)
```

- [ ] **Step 4: Run to verify failure**

Run: `uv run pytest tests/test_evaluate_tools.py tests/test_evaluate_agent.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'casus.evaluate.tools'`.

- [ ] **Step 5: Implement**

Create `src/casus/evaluate/tools.py`:

```python
"""The evaluate agent's nine tools: the fixed queries, as text, and `show`.

Every tool is a thin call into `queries`, bound to one
study when the tools are built. A name the study does not have comes back as a
refusal that lists what it does have, so the model can correct itself; the
workshop and the study draw a refusal red.
"""

from __future__ import annotations

from lingo.tools import tool
from lovelaice.agent import AgentTool, ToolResult

from ..studies import Study
from . import queries

TOOL_NAMES = (
    "list_runs",
    "series",
    "finals",
    "events",
    "ledger",
    "choices",
    "read_scenario",
    "read_rules",
    "show",
)


REFUSED = "refused: "


def _ok(text: str) -> ToolResult:
    return ToolResult(content=[{"type": "text", "text": text}])


def _refused(text: str) -> ToolResult:
    """A refusal opens with `REFUSED`, so a saved chat, which keeps a tool's text
    and not its error flag, still shows it as one."""
    return ToolResult(content=[{"type": "text", "text": REFUSED + text}], is_error=True)


def build_tools(study: Study) -> list[AgentTool]:
    """The evaluate agent's tool set, bound to one study."""

    def answer(query, *args) -> ToolResult:
        try:
            return _ok(queries.render(query(study, *args)))
        except queries.QueryError as exc:
            return _refused(str(exc))

    @tool
    async def list_runs() -> ToolResult:
        """Each run in the study: id, seed, turns completed, status, and each actor's displayed quantities at the end. Call it first."""  # noqa: E501
        return answer(queries.runs)

    @tool
    async def series(quantity: str, holder: str) -> ToolResult:
        """One quantity over time, as a table of turn by run; its header gives the ref that ledger takes.

        Args:
            quantity: a resource of an actor, or an attribute of a place or entity
            holder: the id of that actor, place or entity
        """  # noqa: E501
        return answer(queries.series, quantity, holder)

    @tool
    async def finals(quantity: str, holder: str) -> ToolResult:
        """The value in each run's last recorded state, with min, median, max and the spread.

        Args:
            quantity: a resource of an actor, or an attribute of a place or entity
            holder: the id of that actor, place or entity
        """
        return answer(queries.finals, quantity, holder)

    @tool
    async def events(id: str | None = None) -> ToolResult:
        """How many times each event happened in each run, and on which turns.

        Args:
            id: one event id, or leave it out for every event
        """
        return answer(queries.events, id)

    @tool
    async def ledger(ref: str, run: str) -> ToolResult:
        """Every change to one value in one run (turn, phase, rule, before, after, change), and which rules raised or lowered it.

        Args:
            ref: the value's ref as series or finals print it, e.g. actor.BLUE.stamina
            run: a run id, or its seed
        """  # noqa: E501
        return answer(queries.ledger, ref, run)

    @tool
    async def choices(actor: str | None = None) -> ToolResult:
        """The action types each actor declared, counted per run and listed per turn.

        Args:
            actor: one actor id, or leave it out for every actor
        """
        return answer(queries.choices, actor)

    @tool
    async def read_scenario() -> ToolResult:
        """The scenario data of this study's version, as YAML."""
        return answer(queries.read_scenario)

    @tool
    async def read_rules() -> ToolResult:
        """The rules source of this study's version, exactly as the runs executed it."""
        return answer(queries.read_rules)

    @tool
    async def show(quantity: str, holder: str) -> ToolResult:
        """Switch the chart on screen to this series; it returns nothing you need.

        Args:
            quantity: a resource of an actor, or an attribute of a place or entity
            holder: the id of that actor, place or entity
        """
        try:
            queries.series(study, quantity, holder)  # a wrong name fails here, not on screen
        except queries.QueryError as exc:
            return _refused(str(exc))
        return _ok(f"the chart shows {quantity} of {holder}")

    return [
        AgentTool(inner=list_runs, kind="read"),
        AgentTool(inner=series, kind="read", title_template="series({quantity}, {holder})"),
        AgentTool(inner=finals, kind="read", title_template="finals({quantity}, {holder})"),
        AgentTool(inner=events, kind="read"),
        AgentTool(inner=ledger, kind="read", title_template="ledger({ref}, {run})"),
        AgentTool(inner=choices, kind="read"),
        AgentTool(inner=read_scenario, kind="read"),
        AgentTool(inner=read_rules, kind="read"),
        AgentTool(inner=show, kind="other", title_template="show({quantity}, {holder})"),
    ]
```

The tool docstrings' first lines run past 96 columns on purpose, as in slice 6: lovelaice lists each tool in the system prompt by the first line of its description.

Create `src/casus/evaluate/agent.py`:

```python
"""The evaluate agent: a lovelaice agent with the nine tools and nothing else.

Built the way the design agent is (`casus.design.agent`): `build_evaluate_agent`
binds the tools to one study and loads that study's chat from the session
directory; `EvaluateAgent.turn` runs one question and sends the browser's
messages. After a turn, `unsupported()` checks the answer's figures against
every tool result of the session.
"""

from __future__ import annotations

import pathlib
import re
from collections.abc import Callable
from typing import Any

from lovelaice.agent import Agent, AgentConfig, Session
from lovelaice.agent.events import (
    AssistantMessageDelta,
    AssistantMessageFinalized,
    ToolExecutionEnd,
    ToolExecutionStart,
)
from lovelaice.agent.loops.react_native import ReActNative

from ..studies import Study
from .checker import unsupported_numbers
from .tools import build_tools

SYSTEM_PROMPT = """\
You answer questions about a study of casus, a conflict simulator: every
recorded run of one version of one scenario ({scenario}, version {version}).
All of its numbers come from deterministic rules, never from the players.

Your tools are fixed queries over the transcripts. You cannot run code, and you
never compute a number yourself: no differences, ratios, averages or rounding
of your own. Every figure you write must appear in a tool result of this
conversation; a checker marks any figure that does not, and the room sees the
mark. If a question needs a figure no tool returns, say so and name the figure.

How you work:
- Start with list_runs.
- When you talk about a quantity, call show for it, so the chart on screen
  follows you.
- To explain why a value moved or never moved, read its ledger (series and
  finals print the ref it takes), then read_rules to see which rules can change
  it and under what conditions.
- Name the runs each claim rests on, by seed. State how many runs a
  generalisation covers. A pattern in two or three runs may be the seeds: when
  the study is too small to tell, say so and suggest adding runs.
- Answer in the language of the question, in a few sentences.
"""

Send = Callable[[dict], Any]


def _text(result: Any) -> str:
    content = getattr(result, "content", None) or []
    first = content[0] if content else {}
    return str(first.get("text", "")) if isinstance(first, dict) else ""


def session_path(study: Study, session_dir: pathlib.Path) -> pathlib.Path:
    """One chat per study, beside the design chats and never inside a scenario."""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", study.scenario)
    return pathlib.Path(session_dir) / "studies" / f"{name}-{study.version}.jsonl"


def exchanges(messages: list) -> list[dict]:
    """A session as question-and-answer exchanges: the question, the tool calls
    with their results, the answer, and the answer's figures that no tool result
    of the session had returned by the time the answer ended."""
    out: list[dict] = []
    results: list[str] = []
    for m in messages:
        content = m.content if isinstance(m.content, str) else ""
        if m.role == "user" and content != ReActNative.EMPTY_TURN_NUDGE:
            out.append({"question": content, "answer": "", "tools": [], "_upto": len(results)})
        elif not out:
            continue
        elif m.role == "assistant":
            if content.strip():
                out[-1]["answer"] = (out[-1]["answer"] + "\n\n" + content.strip()).strip()
            for call in m.tool_calls or []:
                entry = {"id": call.id, "name": call.name, "args": call.arguments, "result": ""}
                out[-1]["tools"].append(entry)
        elif m.role == "tool":
            results.append(content)
            out[-1]["_upto"] = len(results)
            for entry in out[-1]["tools"]:
                if entry["id"] == m.tool_call_id:
                    entry["result"] = content
    for exchange in out:
        upto = exchange.pop("_upto")
        exchange["unsupported"] = unsupported_numbers(exchange["answer"], results[:upto])
    return out


def history(study: Study, session_dir: pathlib.Path) -> list[dict]:
    """A study's saved chat, read without building an agent."""
    path = session_path(study, session_dir)
    if not path.is_file():
        return []
    return exchanges(Session.load(path).messages_for_llm("")[1:])


class EvaluateAgent:
    """One agent turn at a time, its events translated for the study screen."""

    def __init__(self, agent: Agent):
        self.agent = agent
        self._send: Send | None = None
        self._streamed = False
        agent.subscribe(self._on_event)

    async def turn(self, text: str, send: Send) -> str:
        """Run one question. `send` receives delta, tool_start and tool_end
        messages; the caller sends done, with `unsupported()`."""
        self.agent.harness.abort.clear()
        self._send, self._streamed = send, False
        try:
            stop = await self.agent.prompt(text)
        finally:
            self._send = None
        return str(getattr(stop, "value", stop))

    def unsupported(self) -> list[str]:
        """The last answer's figures that no tool result of the session supports."""
        turns = exchanges(self.agent.messages_for_llm()[1:])
        return turns[-1]["unsupported"] if turns else []

    def _on_event(self, event: Any) -> None:
        send = self._send
        if send is None:
            return
        if isinstance(event, AssistantMessageDelta):
            self._streamed = True
            send({"type": "delta", "text": event.text})
        elif isinstance(event, AssistantMessageFinalized):
            content = event.message.content if isinstance(event.message.content, str) else ""
            if content.strip() and not self._streamed:  # a model that does not stream
                send({"type": "delta", "text": content})
            self._streamed = False
        elif isinstance(event, ToolExecutionStart):
            send({"type": "tool_start", "id": event.call_id, "name": event.name,
                  "args": event.args})  # fmt: skip
        elif isinstance(event, ToolExecutionEnd):
            send({"type": "tool_end", "id": event.call_id, "ok": not event.is_error,
                  "result": _text(event.result)})  # fmt: skip


def build_evaluate_agent(
    study: Study, settings: Any, session_dir: pathlib.Path
) -> EvaluateAgent:
    config = AgentConfig(
        model=settings.agent_model,
        system_prompt=SYSTEM_PROMPT.format(scenario=study.scenario, version=study.version),
        cwd=f"study {study.scenario} {study.version}",  # shown in the prompt; never a path
        api_key=settings.api_key,
        base_url=settings.endpoint,
    )
    agent = Agent(
        config=config,
        tools=build_tools(study),
        loop=ReActNative(),
        session_path=session_path(study, session_dir),
    )
    return EvaluateAgent(agent)
```

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/test_evaluate_tools.py tests/test_evaluate_agent.py tests/test_purity.py -q`
Expected: PASS (5 + 7 tests, and the purity test).

- [ ] **Step 7: Break it on purpose**

Make `EvaluateAgent.unsupported` return `[]`. Run `uv run pytest tests/test_evaluate_agent.py -q -k derived`. Expected: FAIL. Revert.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock .github/workflows/tests.yml tests/test_purity.py \
  src/casus/evaluate/tools.py src/casus/evaluate/agent.py tests/evaluate_support.py \
  tests/test_evaluate_tools.py tests/test_evaluate_agent.py
git commit -m "feat(evaluate): the evaluate agent, its nine tools and the figure check"
```

(Leave out of `git add` any of the first four files this step did not change.)

---

### Task 7: The chat endpoints

**Files:**
- Modify: `src/casus/server/study.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `build_evaluate_agent`, `history` (Task 6, imported inside the endpoints only); `sse.event_stream` (slice 3); `casus.settings.redact` (slice 5).
- Produces: `lock_for(scenario, version) -> asyncio.Lock`, `session_dir()` in `casus.server.study`, and:
  - `GET /api/studies/{scenario}/{version}/chat` → `{busy, exchanges}`: `exchanges` is the saved chat, each answer with its `unsupported` figures.
  - `POST /api/studies/{scenario}/{version}/chat` with `{text}` → `text/event-stream` of the master plan's agent messages, ending with `{"type": "done", "unsupported": [...]}` and slice 3's close event; `409` while the agent answers another question on the study.

As in slice 6, an error inside a turn arrives as a `delta` before `done`, its text through `redact`, and `done` goes out after the lock is released, so a browser that asks again the moment it sees `done` is not refused. `session_dir()` is the design router's directory; a study's chat sits under `studies/` in it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_server.py`, add `import json` to the imports, change the `evaluate_support` import to `from evaluate_support import QUESTION, Analyst, Gauge, record_study`, and append:

```python
def _events(body: str) -> list[dict]:
    """The agent's messages in an event stream, the closing event left out."""
    found = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    return [m for m in found if "type" in m]


def test_the_chat_streams_agent_events_and_ends_with_the_check(
    study_client, study_runs, monkeypatch
):
    monkeypatch.setattr("lovelaice.agent.agent._build_llm", lambda cfg: Analyst(invent=True))
    url = f"/api/studies/smoke/{_study(study_runs).version}/chat"
    body = study_client.post(url, json={"text": QUESTION}).text
    messages = _events(body)
    assert {m["type"] for m in messages} >= {"delta", "tool_start", "tool_end", "done"}
    done = messages[-1]
    assert done["type"] == "done" and len(done["unsupported"]) == 1
    [exchange] = study_client.get(url).json()["exchanges"]
    assert exchange["question"] == QUESTION and exchange["unsupported"] == done["unsupported"]


def test_an_agent_that_fails_says_why_through_redact(study_client, study_runs, monkeypatch):
    class Refusing(Analyst):
        async def chat(self, messages, tools=None, **kwargs):
            raise RuntimeError("401 for key sk-secret")

    monkeypatch.setattr("lovelaice.agent.agent._build_llm", lambda cfg: Refusing())
    def redact(text, secrets=None):
        return text.replace("sk-secret", "[redacted]")

    monkeypatch.setattr("casus.settings.redact", redact)
    url = f"/api/studies/smoke/{_study(study_runs).version}/chat"
    body = study_client.post(url, json={"text": QUESTION}).text
    assert "RuntimeError: 401 for key [redacted]" in body and "sk-secret" not in body
    assert _events(body)[-1] == {"type": "done", "unsupported": []}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_server.py -q -k "chat or agent"`
Expected: FAIL: the chat routes are 404s.

- [ ] **Step 3: Implement**

In `src/casus/server/study.py`, add `from fastapi.responses import StreamingResponse` and `from . import sse` to the imports. Add after `class BatchIn`:

```python
BUSY = "the evaluate agent is answering a question about this study"

_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}
_TASKS: set[asyncio.Task] = set()


class TextIn(BaseModel):
    text: str = Field(min_length=1)


def lock_for(scenario: str, version: str) -> asyncio.Lock:
    return _LOCKS.setdefault((scenario, version), asyncio.Lock())


def session_dir() -> pathlib.Path:
    """The same directory the design chats use; a study's chat is under
    `studies/` in it."""
    from ..settings import data_dir

    return data_dir() / "sessions"
```

and inside `router`, just before `return api`:

```python
    @api.get("/{scenario}/{version}/chat")
    def chat_state(scenario: str, version: str) -> dict:
        from ..evaluate.agent import history

        study = find(scenario, version)
        return {
            "busy": lock_for(scenario, version).locked(),
            "exchanges": history(study, session_dir()),
        }

    @api.post("/{scenario}/{version}/chat")
    async def chat(scenario: str, version: str, body: TextIn) -> StreamingResponse:
        study = find(scenario, version)
        held = lock_for(scenario, version)
        if held.locked():
            raise HTTPException(409, BUSY)
        await held.acquire()  # uncontended, so no await point between check and take
        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def work() -> None:
            from ..settings import redact

            evaluate = None
            try:
                from ..evaluate.agent import build_evaluate_agent

                evaluate = build_evaluate_agent(study, current_settings(), session_dir())
                await evaluate.turn(body.text, queue.put_nowait)
            except Exception as exc:  # the stream must still end, and say why
                text = redact(f"{type(exc).__name__}: {exc}")
                queue.put_nowait({"type": "delta", "text": f"\n{text}"})
            finally:
                unsupported = evaluate.unsupported() if evaluate is not None else []
                held.release()
                queue.put_nowait({"type": "done", "unsupported": unsupported})

        task = asyncio.create_task(work())
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)

        async def messages():
            while True:
                message = await queue.get()
                yield message
                if message["type"] == "done":
                    return

        return sse.event_stream(messages())
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_server.py -q`
Expected: PASS.

- [ ] **Step 5: Break it on purpose**

In `work`, replace `text = redact(f"{type(exc).__name__}: {exc}")` with `text = f"{type(exc).__name__}: {exc}"`. Run `uv run pytest tests/test_server.py -q -k through_redact`. Expected: FAIL (`sk-secret` reaches the stream). Revert.

- [ ] **Step 6: Commit**

```bash
git add src/casus/server/study.py tests/test_server.py
git commit -m "feat(server): the evaluate agent's chat, checked answer by answer"
```

---

### Task 8: The study screen and the home shelf

**Files:**
- Create: `ui/js/study.js`
- Modify: `ui/js/i18n.js`, `ui/js/shell.js`, `ui/css/app.css`, `src/casus/server/app.py`
- Test: `tests/js/harness.js`, `tests/test_ui_scripts.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `Casus.records.RunModel`, `.label`; `Casus.map.esc`; `Casus.card.fmt`; `Casus.i18n.t`, `.use`; `Casus.shell.route`, `.onHome`, `.json` (slice 1); every endpoint of Tasks 5 and 7, and `GET /api/runs/{id}` (slice 1).
- Produces: the route `#/study/<scenario>/<version>`; `Casus.study = {mark, footer, holders}`; on the home, study cards with `data-study`, `data-version`, `data-current` and, in `[data-actions="study"]`, **Evaluate** and **Add runs**. `Casus.shell.route` handlers now receive every path segment after the name: `fn(view, arg, ...rest)`.

The home's second shelf becomes studies: one card per study from `GET /api/studies`, in its order (by scenario, each scenario's versions newest first), labelled with the version and the date, and "older rules" when it is not the current version. **Add runs** is disabled on an older version, with the reason in its title. It opens an inline confirmation that fetches the plan and states `runs × turns × (actors + 1) = calls` before **Start**. The study screen fetches each run's viewer records once (a finished run never changes) for the run cards' counts and the chart's selectors, draws the chart from `/series`, and polls `/api/studies` every three seconds so batch runs appear as they land. The chat pane draws tool lines as they start and end, follows a successful `show` by switching the chart, and on `done` marks the answer's unsupported figures and adds the footer count.

- [ ] **Step 1: Write the failing tests**

In `tests/js/harness.js`, add before `process.stdout.write(JSON.stringify(out));`:

```js
if (input.mark) out.marked = Casus.study.mark(input.mark.text, input.mark.unsupported);
```

Append to `tests/test_ui_scripts.py`:

```python
# --- the study screen's marks (slice 7) ----------------------------------------------

STUDY_SCRIPTS = "i18n.js,records.js,map.js,card.js,shell.js,study.js"


def _mark(text: str, unsupported: list[str]) -> str:
    payload = json.dumps(
        {"records": [], "labels": [], "mark": {"text": text, "unsupported": unsupported}}
    )
    done = subprocess.run(
        [NODE, str(HARNESS), STUDY_SCRIPTS],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)["marked"]


def test_an_unsupported_figure_is_marked_every_time_it_appears():
    html = _mark("a fall of 44.2 points, 44.2 in all", ["44.2"])
    assert html.count('<mark class="unsup"') == 2


def test_a_figure_is_marked_whole_never_inside_another_number_or_an_identifier():
    html = _mark("144.25 and 44.2 and smoke-4 and 4", ["44.2", "4"])
    assert html.count("<mark") == 2
    assert "144.25" in html and "smoke-4" in html


def test_the_answer_is_escaped_before_it_is_marked():
    html = _mark("<b>22</b> & 23", ["23"])
    assert "&lt;b&gt;22&lt;/b&gt; &amp; <mark" in html


def test_nothing_is_marked_when_every_figure_is_supported():
    assert "<mark" not in _mark("it ended at 22", [])
```

Append to `tests/test_server.py`:

```python
def test_the_home_page_loads_study_js_after_the_shell(study_client):
    html = study_client.get("/").text
    assert html.index("/ui/js/shell.js") < html.index("/ui/js/study.js")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ui_scripts.py tests/test_server.py -q -k "mark or study_js"`
Expected: FAIL (node cannot read `ui/js/study.js`; the home page loads no `study.js`).

- [ ] **Step 3: The strings**

In `ui/js/i18n.js`, change `studies: "Runs"` to `studies: "Studies"` and `studies: "Partidas"` to `studies: "Estudios"`, then add to the `en` table:

```js
      version: "version", older: "older rules", evaluate: "Evaluate", add_runs: "Add runs",
      older_rules: "Older rules: runs can only be added to the scenario's current version.",
      runs_n: "runs", calls_at_most: "model calls at most", seeds: "seeds", start: "Start",
      cancel: "Cancel", agent_title: "Evaluate agent",
      agent_hint: "Answers from fixed queries over the transcripts. " +
        "A figure no query returned is marked.",
      agent_intro: "Ask about something that varies between runs, " +
        "or something that comes out the same in all of them.",
      ask: "Ask about the study…", send: "Send", series: "Series", of: "of",
      one_line: "one line per run", actions: "actions", seed: "seed", actors: "Actors",
      places: "Places", entities: "Entities",
      unsupported_one: "figure not found in any query",
      unsupported_many: "figures not found in any query",
      unsupported_title: "no query returned this figure",
      agent_error: "The agent stopped:", no_values: "no values for this series",
      q_vary: "What changes between runs, and what stays the same?",
      q_chart: "Why does {q} of {h} end where it does?",
```

and to the `es` table:

```js
      version: "versión", older: "reglas anteriores", evaluate: "Evaluar",
      add_runs: "Añadir corridas",
      older_rules: "Reglas anteriores: solo se añaden corridas " +
        "a la versión actual del escenario.",
      runs_n: "corridas", calls_at_most: "llamadas al modelo como máximo", seeds: "semillas",
      start: "Lanzar", cancel: "Cancelar", agent_title: "Agente de evaluación",
      agent_hint: "Responde con consultas fijas sobre las transcripciones. " +
        "Se marca toda cifra que ninguna consulta devolvió.",
      agent_intro: "Pregunta por algo que varíe entre corridas, " +
        "o por algo que sale igual en todas.",
      ask: "Pregunta sobre el estudio…", send: "Enviar", series: "Serie", of: "de",
      one_line: "un trazo por corrida", actions: "acciones", seed: "semilla", actors: "Actores",
      places: "Lugares", entities: "Entidades",
      unsupported_one: "cifra que ninguna consulta devolvió",
      unsupported_many: "cifras que ninguna consulta devolvió",
      unsupported_title: "ninguna consulta devolvió esta cifra",
      agent_error: "El agente se detuvo:", no_values: "esta serie no tiene valores",
      q_vary: "¿Qué cambia entre corridas y qué sale igual?",
      q_chart: "¿Por qué {q} de {h} termina donde termina?",
```

- [ ] **Step 4: The home shelf and the router in `ui/js/shell.js`**

Replace the whole `home` function with:

```js
  async function home() {
    const [scenarios, found] =
      await Promise.all([json("/api/scenarios"), json("/api/studies")]);
    const t = C.i18n.t;
    const runRow = (r) => `<div class="runrow">
      <div class="meta">${esc(r.id)}<br>
        ${r.turns_done}/${r.turns_planned} · ${esc(r.status)}</div>
      <button class="btn small" onclick="location.hash='#/view/${encodeURIComponent(r.id)}'">` +
      `${t("view")} ▸</button></div>`;
    view().innerHTML = `
      <div class="home">
        <div class="hero"><h1>cas<i>us</i></h1></div>
        <section class="shelf"><h2>${t("scenarios")}</h2>
          <div class="row">${scenarios.map((s) => `
          <div class="card" data-scenario="${esc(s.dir)}"><h3>${esc(s.name)}</h3>
            <div class="meta">${s.actors} · ${s.places} · ${s.turns}</div>
            <p>${esc(s.description || "")}</p>
            <div class="acts"><span class="badge ${s.valid ? "ok" : "bad"}">` +
            `${s.valid ? "✓" : "✗ " + esc(s.findings[0] || "")}</span></div>
            <div class="acts" data-actions="scenario"></div></div>`).join("")}</div></section>
        <section class="shelf"><h2>${t("studies")}</h2><div class="row">${found.map((s) => `
          <div class="card" data-study="${esc(s.scenario)}" data-version="${esc(s.version)}"
               data-current="${s.current}">
            <h3>${esc(s.scenario)} <span class="meta">· ${s.runs.length}</span></h3>
            <div class="meta">${t("version")} ${esc(s.version)} · ${esc(s.date)}` +
            `${s.current ? "" : ` · ${t("older")}`}</div>
            <div class="runlist">${s.runs.map(runRow).join("")}</div>
            <div class="acts" data-actions="study"></div></div>`).join("")}</div></section>
      </div>`;
    for (const fn of hooks.home) fn(view());
  }
```

Slice 1's `dispatch` already passes every path segment after the route name, so `Casus.shell.route("study", (view, scenario, version) => ...)` receives both. Check with `grep -n "\.\.\.args" ui/js/shell.js`.

- [ ] **Step 5: Create `ui/js/study.js`**

```js
// The study: every run of one version of one scenario. Run cards, one series
// chart with a line per run, and the evaluate agent. The chart's values come
// from /series and the agent's figures are checked on the server; this file
// only draws them and marks the figures no query returned.
(function () {
  const C = (window.Casus = window.Casus || {});
  const t = (k) => C.i18n.t(k);
  const esc = (s) => C.map.esc(s);
  const RUNC = ["#4fa3ff", "#ff5a6e", "#3ddc97", "#f5c451", "#a98bff", "#ff9e5e", "#4fd1b5",
                "#e07ee0", "#7ee081", "#8ab4ff"];
  const NOT_QUANTITIES = new Set(["lat", "lon"]);   // map coordinates, drawn by map.js
  const REFUSED = "refused: ";   // how evaluate/tools.py opens a refusal
  const JSON_POST = { method: "POST", headers: { "content-type": "application/json" } };

  // The answer as HTML with every unsupported figure wrapped in <mark>. A figure
  // is matched whole, never inside a longer number or an identifier like smoke-4.
  function mark(text, unsupported) {
    const html = esc(text);
    const figures = [...new Set(unsupported || [])].sort((a, b) => b.length - a.length);
    if (!figures.length) return html;
    const alt = figures.map((f) => esc(f).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
    const re = new RegExp(`(?<![\\p{L}\\p{N}_.,])(?<![\\p{L}\\p{N}]-)(${alt})` +
                          `(?![\\p{L}\\p{N}_]|[.,]\\p{N})`, "gu");
    const title = esc(t("unsupported_title"));
    return html.replace(re, `<mark class="unsup" title="${title}">$1</mark>`);
  }

  function footer(unsupported) {
    const n = (unsupported || []).length;
    if (!n) return "";
    const key = n === 1 ? "unsupported_one" : "unsupported_many";
    return `<div class="foot">${n} ${t(key)}</div>`;
  }

  // What a series can be drawn for: each holder in the first recorded state,
  // with its numeric quantities.
  function holders(run) {
    const first = run.turns.find((x) => x.before);
    if (!first) return [];
    const s = first.before, out = [];
    const numeric = (o) => Object.keys(o || {})
      .filter((k) => typeof o[k] === "number" && !NOT_QUANTITIES.has(k));
    for (const id of Object.keys(s.actors || {}).sort()) {
      out.push({ id, group: "actors", q: numeric(s.actors[id].resources) });
    }
    for (const id of Object.keys(s.places || {})) {
      out.push({ id, group: "places", q: numeric(s.places[id].attrs) });
    }
    for (const e of s.entities || []) {
      out.push({ id: e.id, group: "entities", q: numeric(e.attrs) });
    }
    return out.filter((h) => h.q.length);
  }

  function counts(run) {
    let actions = 0, mutations = 0;
    for (const x of run.turns) { actions += x.actions.length; mutations += x.mutations; }
    return { actions, mutations };
  }

  // The inline confirmation for a batch: how many runs, and what that costs in
  // model calls, before anything starts.
  function addRuns(container, scenario, started) {
    if (container.querySelector(".batch")) return;
    container.insertAdjacentHTML("beforeend", `<div class="batch">
      <label>${t("runs_n")} <input type="number" min="1" max="100" value="10"></label>
      <span class="calls meta"></span>
      <button class="btn primary" data-start>${t("start")}</button>
      <button class="btn" data-cancel>${t("cancel")}</button></div>`);
    const box = container.querySelector(".batch"), input = box.querySelector("input");
    const base = `/api/studies/${encodeURIComponent(scenario)}`;
    const n = () => Number(input.value) || 1;
    async function plan() {
      const p = await C.shell.json(`${base}/plan?n=${n()}`);
      box.querySelector(".calls").innerHTML =
        `${p.runs} × ${p.turns} × (${p.actors} + 1) = <b>${p.calls}</b> ${t("calls_at_most")}` +
        ` · ${t("seeds")} ${p.first_seed}–${p.last_seed}`;
    }
    input.oninput = plan;
    box.querySelector("[data-cancel]").onclick = () => box.remove();
    box.querySelector("[data-start]").onclick = async () => {
      const r = await fetch(`${base}/runs`, { ...JSON_POST, body: JSON.stringify({ n: n() }) });
      const body = await r.json();
      if (!r.ok) { box.querySelector(".calls").textContent = body.detail || r.status; return; }
      box.remove();
      started(body.ids);
    };
    plan();
  }

  C.shell.onHome((root) => {
    for (const card of root.querySelectorAll("[data-study]")) {
      const acts = card.querySelector('[data-actions="study"]');
      const s = card.dataset.study, v = card.dataset.version;
      const current = card.dataset.current === "true";
      const go = () => {
        location.hash = `#/study/${encodeURIComponent(s)}/${encodeURIComponent(v)}`;
      };
      const locked = current ? "" : ` disabled title="${esc(t("older_rules"))}"`;
      acts.insertAdjacentHTML("beforeend",
        `<button class="btn primary" data-evaluate>⌕ ${t("evaluate")}</button>` +
        `<button class="btn" data-add-runs${locked}>＋ ${t("add_runs")}</button>`);
      acts.querySelector("[data-evaluate]").onclick = go;
      acts.querySelector("[data-add-runs]").onclick = () => addRuns(acts, s, go);
    }
  });

  async function mount(root, scenario, version) {
    const base = `/api/studies/${encodeURIComponent(scenario)}/${encodeURIComponent(version)}`;
    const S = { study: null, models: new Map(), options: [], timer: 0, busy: false,
                abort: new AbortController() };
    const find = async () => (await C.shell.json("/api/studies"))
      .find((s) => s.scenario === scenario && s.version === version);
    S.study = await find();
    if (!S.study) {
      root.innerHTML = `<div class="nomap">${esc(scenario)} · ${esc(version)}: 404</div>`;
      return null;
    }
    // A finished run's records never change, so each is fetched once.
    const model = async (info) => {
      const known = S.models.get(info.id);
      if (known && known.status === info.status && info.status !== "incomplete") {
        return known.run;
      }
      const run = new C.records.RunModel();
      const records = await C.shell.json("/api/runs/" + encodeURIComponent(info.id));
      for (const r of records) run.push(r);
      S.models.set(info.id, { status: info.status, run });
      return run;
    };
    const first = await model(S.study.runs[0]);
    C.i18n.use((first.header && first.header.language) || "en");
    const L = (k) => esc(C.records.label(first, k));

    root.innerHTML = `<div class="split2">
      <div class="agent">
        <div class="ah"><b>${t("agent_title")}</b><div>${t("agent_hint")}</div></div>
        <div class="log" id="log"></div>
        <div class="ask">
          <div class="suggest">
            <button data-q="q_vary"></button><button data-q="q_chart"></button></div>
          <div class="askrow"><textarea id="q" placeholder="${esc(t("ask"))}"></textarea>
            <button class="btn primary" id="send">${t("send")}</button></div>
        </div>
      </div>
      <div class="study">
        <div class="acts" data-actions="study"><b>${esc(scenario)}</b>
          <span class="meta">${t("version")} ${esc(version)}</span>
          <span class="sp"></span></div>
        <div class="runs" id="runs"></div>
        <div class="chartbox">
          <div class="ctl">${t("series")}: <select id="sq"></select>
            ${t("of")} <select id="sh"></select>
            <span class="sp"></span><span class="meta">${t("one_line")}</span></div>
          <div id="chart"></div>
        </div>
      </div></div>`;
    const $ = (s) => root.querySelector(s);

    // ---- runs and the chart ----
    function cards() {
      $("#runs").innerHTML = S.study.runs.map((info, i) => {
        const m = S.models.get(info.id);
        const n = m ? counts(m.run) : { actions: "…", mutations: "…" };
        const failed = m && m.run.error;
        const error = failed ? `<div class="meta bad">${esc(failed.error)}</div>` : "";
        const swatch = `<span class="sw" style="background:${RUNC[i % RUNC.length]}"></span>`;
        const view = `location.hash='#/view/${encodeURIComponent(info.id)}'`;
        return `<div class="runc" data-run="${esc(info.id)}">
          <div>${swatch}<b>${esc(info.id)}</b></div>
          <div class="meta">${t("seed")} ${info.seed} · ${esc(info.status)} · ` +
          `${info.turns_done}/${info.turns_planned}</div>
          <div class="meta">${n.actions} ${t("actions")} · ` +
          `${n.mutations} ${t("mutations")}</div>${error}
          <div><button class="btn small" onclick="${view}">${t("view")} ▸</button></div></div>`;
      }).join("");
    }
    function selectors(holder, quantity) {
      S.options = holders(first);
      $("#sh").innerHTML = ["actors", "places", "entities"].map((g) => {
        const items = S.options.filter((h) => h.group === g);
        if (!items.length) return "";
        const options = items.map((h) => `<option value="${esc(h.id)}">${L(h.id)}</option>`);
        return `<optgroup label="${t(g)}">${options.join("")}</optgroup>`;
      }).join("");
      if (holder) $("#sh").value = holder;
      const h = S.options.find((x) => x.id === $("#sh").value) || S.options[0];
      if (!h) { $("#sq").innerHTML = ""; return; }
      const display = first.scenario.display || {};
      const standing = (display.standing || []).filter((k) => h.q.includes(k));
      const options = h.q.map((k) => `<option value="${esc(k)}">${L(k)}</option>`);
      $("#sq").innerHTML = options.join("");
      $("#sq").value = quantity && h.q.includes(quantity) ? quantity : standing[0] || h.q[0];
      suggestions();
    }
    async function chart() {
      const q = $("#sq").value, h = $("#sh").value;
      const none = () => {
        $("#chart").innerHTML = `<div class="nomap">${t("no_values")}</div>`;
      };
      if (!q || !h) return none();
      const query = `quantity=${encodeURIComponent(q)}&holder=${encodeURIComponent(h)}`;
      const data = await C.shell.json(`${base}/series?${query}`);
      const vals = data.runs.flatMap((r) => r.values).filter((v) => typeof v === "number");
      if (!vals.length) return none();
      const n = data.turns.length, lo = Math.min(0, ...vals), hi = Math.max(...vals) * 1.1 || 1;
      const W = 900, H = 320, l = 44, r = 150, tp = 14, b = 30;
      const X = (i) => l + (n > 1 ? i / (n - 1) : 0.5) * (W - l - r);
      const Y = (v) => tp + (1 - (v - lo) / (hi - lo)) * (H - tp - b);
      let s = `<svg viewBox="0 0 ${W} ${H}" data-quantity="${esc(q)}" data-holder="${esc(h)}">`;
      for (let k = 0; k <= 4; k++) {
        const v = lo + ((hi - lo) * k) / 4;
        s += `<line class="gl" x1="${l}" x2="${W - r}" y1="${Y(v)}" y2="${Y(v)}"/>` +
             `<text class="tick" x="${l - 8}" y="${Y(v) + 3}" text-anchor="end">` +
             `${C.card.fmt(v)}</text>`;
      }
      data.turns.forEach((turn, i) => {
        s += `<text class="tick" x="${X(i)}" y="${H - 10}" text-anchor="middle">${turn}</text>`;
      });
      const ends = [];
      for (const run of data.runs) {
        const col = RUNC[S.study.runs.findIndex((x) => x.id === run.id) % RUNC.length];
        let seg = [], last = null;
        const flush = () => {
          if (seg.length) {
            s += `<polyline fill="none" stroke="${col}" stroke-width="2.5" ` +
                 `data-run="${esc(run.id)}" points="${seg.join(" ")}"/>`;
          }
          seg = [];
        };
        run.values.forEach((v, i) => {
          if (typeof v !== "number") { flush(); return; }
          seg.push(`${X(i)},${Y(v)}`); last = [i, v];
          const tip = `${t("seed")} ${run.seed} · ${t("day")} ${data.turns[i]}: ` +
                      C.card.fmt(v);
          s += `<circle cx="${X(i)}" cy="${Y(v)}" r="3" fill="${col}">` +
               `<title>${tip}</title></circle>`;
        });
        flush();
        if (last) {
          ends.push({ x: X(last[0]) + 10, y: Y(last[1]) + 4, col,
                      text: `${t("seed")} ${run.seed} · ${C.card.fmt(last[1])}` });
        }
      }
      // End labels in value order, pushed apart so runs that end close stay readable.
      ends.sort((a, c) => a.y - c.y);
      ends.forEach((e, i) => { if (i && e.y - ends[i - 1].y < 13) e.y = ends[i - 1].y + 13; });
      for (const e of ends) {
        s += `<text x="${e.x}" y="${e.y}" fill="${e.col}" font-size="12">${esc(e.text)}</text>`;
      }
      $("#chart").innerHTML = s + "</svg>";
    }
    function follow(args) {
      if (!S.options.some((x) => x.id === args.holder)) return;
      selectors(args.holder, args.quantity);
      chart();
    }
    $("#sh").onchange = () => { selectors($("#sh").value); chart(); };
    $("#sq").onchange = () => { suggestions(); chart(); };

    const shape = (study) =>
      JSON.stringify(study.runs.map((r) => [r.id, r.status, r.turns_done]));
    async function refresh() {
      const now = await find();
      if (!now) return;
      const changed = shape(now) !== shape(S.study);
      S.study = now;
      await Promise.all(now.runs.map(model));
      cards();
      if (changed) chart();
    }

    // ---- the agent ----
    const log = $("#log");
    const scroll = () => { log.scrollTop = log.scrollHeight; };
    function user(text) {
      log.insertAdjacentHTML("beforeend", `<div class="msg user">${esc(text)}</div>`);
      scroll();
    }
    function bot(text, unsupported) {
      const html = mark(text, unsupported);
      log.insertAdjacentHTML("beforeend", `<div class="msg bot">${html}</div>`);
      scroll();
      return { el: log.lastElementChild, raw: text };
    }
    function tool(name, args, result, ok) {
      const shown = Object.entries(args || {})
        .map(([k, v]) => `${esc(k)}=${esc(JSON.stringify(v))}`);
      log.insertAdjacentHTML("beforeend", `<div class="tool run">` +
        `<div class="fn">${esc(name)}(${shown.join(", ")})</div><div class="res"></div></div>`);
      const entry = { el: log.lastElementChild, name, args };
      if (result !== null) end(entry, ok, result);
      scroll();
      return entry;
    }
    function end(entry, ok, result) {
      entry.el.className = `tool ${ok ? "ok" : "bad"}`;
      const lines = String(result || "").split("\n");
      entry.el.querySelector(".res").textContent =
        lines.slice(0, 4).join("\n") + (lines.length > 4 ? "\n…" : "");
    }
    function suggestions() {
      const h = C.records.label(first, $("#sh").value);
      const q = C.records.label(first, $("#sq").value);
      root.querySelector('[data-q="q_vary"]').textContent = t("q_vary");
      root.querySelector('[data-q="q_chart"]').textContent =
        t("q_chart").replace("{q}", q).replace("{h}", h);
    }
    async function conversation() {
      const state = await C.shell.json(base + "/chat");
      log.innerHTML = `<div class="msg bot">${esc(t("agent_intro"))}</div>`;
      for (const x of state.exchanges) {
        user(x.question);
        for (const call of x.tools) {
          tool(call.name, call.args, call.result, !call.result.startsWith(REFUSED));
        }
        bot(x.answer, x.unsupported).el.insertAdjacentHTML("afterend", footer(x.unsupported));
      }
    }
    async function ask(text) {
      if (S.busy || !text.trim()) return;
      S.busy = true;
      user(text);
      const calls = {}, bubbles = [];
      let bubble = null;
      function handle(m) {
        if (m.type === "delta") {
          if (!bubble) { bubble = bot("", []); bubbles.push(bubble); }
          bubble.raw += m.text;
          bubble.el.innerHTML = mark(bubble.raw, []);
          scroll();
        } else if (m.type === "tool_start") {
          bubble = null;
          calls[m.id] = tool(m.name, m.args, null, true);
        } else if (m.type === "tool_end" && calls[m.id]) {
          end(calls[m.id], m.ok, m.result);
          if (calls[m.id].name === "show" && m.ok) follow(calls[m.id].args);
        } else if (m.type === "done") {
          for (const b of bubbles) b.el.innerHTML = mark(b.raw, m.unsupported);
          const tail = bubbles.length ? bubbles[bubbles.length - 1].el : log.lastElementChild;
          tail.insertAdjacentHTML("afterend", footer(m.unsupported));
          scroll();
        }
      }
      try {
        const r = await fetch(base + "/chat",
          { ...JSON_POST, signal: S.abort.signal, body: JSON.stringify({ text }) });
        if (!r.ok) { bot(String((await r.json()).detail || r.status), []); return; }
        const reader = r.body.getReader(), dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let i;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            const chunk = buf.slice(0, i);
            buf = buf.slice(i + 2);
            const data = chunk.split("\n").find((line) => line.startsWith("data: "));
            if (data) {
              const message = JSON.parse(data.slice(6));
              if (message.type) handle(message);
            }
          }
        }
      } catch (e) {
        if (e.name !== "AbortError") {
          log.insertAdjacentHTML("beforeend",
            `<div class="foot">${t("agent_error")} ${esc(e.message)}</div>`);
        }
      } finally {
        S.busy = false;
      }
    }
    $("#send").onclick = () => { const q = $("#q"), v = q.value; q.value = ""; ask(v); };
    $("#q").onkeydown = (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#send").onclick(); }
    };
    root.querySelector(".suggest").onclick = (e) => {
      if (e.target.dataset.q) ask(e.target.textContent);
    };
    if (S.study.current) {
      const acts = root.querySelector('.study [data-actions="study"]');
      acts.insertAdjacentHTML("beforeend",
        `<button class="btn" data-add-runs>＋ ${t("add_runs")}</button>`);
      acts.querySelector("[data-add-runs]").onclick = () => addRuns(acts, scenario, refresh);
    }

    selectors();
    await Promise.all(S.study.runs.map(model));
    cards();
    await chart();
    await conversation();
    S.timer = setInterval(refresh, 3000);
    return () => { clearInterval(S.timer); S.abort.abort(); };
  }

  C.shell.route("study", mount);
  C.study = { mark, footer, holders };
})();
```

- [ ] **Step 6: The styles and the script list**

Append to `ui/css/app.css`:

```css
/* ---------- the study (slice 7) ---------- */
.msg.bot{white-space:pre-wrap}
mark.unsup{background:rgba(255,90,110,.16);color:var(--bad);border-bottom:1px dashed var(--bad);
  border-radius:3px;padding:0 2px}
.foot{font-family:var(--mono);font-size:11.5px;color:var(--bad)}
.batch{display:flex;gap:8px;align-items:center;flex-wrap:wrap;width:100%}
.batch input{width:64px;background:#0a1019;border:1px solid var(--line);color:var(--ink);
  border-radius:6px;padding:5px 8px}
.meta.bad{color:var(--bad)}
.study>.acts{align-items:center}
```

The split screen needs `#view` to have a bounded height; slice 1's `#appshell{height:100vh;display:flex;flex-direction:column}` rule provides it. Check with `grep -n "#appshell" ui/css/app.css` before relying on it.

In `src/casus/server/app.py`, append `"study.js"` as the last of the app's scripts, after `workshop.js` when slice 6 is in:

```python
APP_SCRIPTS = (*bundle.SCRIPTS, "shell.js", "workshop.js", "study.js")
```

(or `(*bundle.SCRIPTS, "shell.js", "study.js")` without slice 6).

- [ ] **Step 7: Run to verify it passes**

Run: `uv run pytest tests/test_ui_scripts.py tests/test_server.py -q`
Expected: PASS, including `test_every_ui_script_parses[study.js]`.

- [ ] **Step 8: Commit**

```bash
git add ui/js/study.js ui/js/i18n.js ui/js/shell.js ui/css/app.css src/casus/server/app.py \
  tests/js/harness.js tests/test_ui_scripts.py tests/test_server.py
git commit -m "feat(ui): the study screen, and studies by version on the home shelf"
```

---

### Task 9: The study in a real browser

**Files:**
- Test: `tests/browser/test_app.py`

**Interfaces:**
- Consumes: the `page` fixture and `serve(runs_dir, **app_kwargs)` (slices 1 and 3); `record_study`, `Gauge`, `Analyst`, `QUESTION` (`tests/evaluate_support.py`).

The fixture records its study on a worker thread. Playwright's sync API keeps an event loop running on the test's thread for the whole session, and `engine.run` calls `asyncio.run`, which refuses to start inside a running loop. (Slice 1's own `run_records` calls `engine.run` on the test thread; see the note at the end of this plan.)

- [ ] **Step 1: Write the tests**

In `tests/browser/test_app.py`, add at the top:

```python
import concurrent.futures

import pytest
import yaml
from browser_support import serve
from evaluate_support import QUESTION, SMOKE, Analyst, Gauge, record_study

from casus.server.runs import RunManager
from casus.settings import Settings
```

(merge with any imports an earlier slice put there) and append:

```python
# --- the study (slice 7) ---------------------------------------------------------


@pytest.fixture
def study_app(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    runs = tmp_path / "study-runs"
    runs.mkdir()
    # Playwright's sync API keeps an event loop running on this thread, and
    # recording a run starts one of its own, so the recording runs on another.
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        study = pool.submit(record_study, runs, (1, 2)).result()
    url, stop = serve(
        runs,
        run_manager=RunManager(runs, engine_factory=Gauge().factory),
        settings=Settings.load(path=tmp_path / "absent.toml", env={}),
    )
    yield url, study
    stop()


def _open_study(page, url, study):
    page.goto(f"{url}#/study/{study.scenario}/{study.version}")
    page.wait_for_selector("#chart svg")


def test_the_home_shows_each_study_by_version_with_its_actions(page, study_app):
    url, study = study_app
    page.goto(url)
    card = page.locator(f'[data-study="smoke"][data-version="{study.version}"]')
    card.wait_for()
    assert card.locator(".runrow").count() == len(study.runs)
    assert card.locator("[data-evaluate]").is_visible()
    assert card.locator("[data-add-runs]").is_enabled()


def test_add_runs_states_the_cost_then_the_runs_land_in_the_study(page, study_app):
    url, study = study_app
    data = yaml.safe_load((SMOKE / "scenario.yaml").read_text())
    per_run = data["turns"] * (len(data["actors"]) + 1)
    page.goto(url)
    card = page.locator(f'[data-study="smoke"][data-version="{study.version}"]')
    card.locator("[data-add-runs]").click()
    calls = card.locator(".batch .calls b")
    calls.wait_for()
    assert calls.inner_text() == str(10 * per_run)
    card.locator(".batch input").fill("2")
    page.wait_for_function(
        "(want) => document.querySelector('.batch .calls b').textContent === want",
        arg=str(2 * per_run),
    )
    card.locator("[data-start]").click()
    page.wait_for_selector("#chart svg")
    want = len(study.runs) + 2
    page.wait_for_function(
        "(want) => document.querySelectorAll('.runc').length === want", arg=want, timeout=15000
    )


def test_the_study_draws_one_line_per_run_and_follows_the_selectors(page, study_app):
    url, study = study_app
    _open_study(page, url, study)
    assert page.locator(".runc").count() == len(study.runs)
    assert page.locator("#chart polyline").count() == len(study.runs)
    page.select_option("#sh", "border")
    page.wait_for_selector('#chart svg[data-holder="border"]')
    assert page.locator("#sq").input_value() == "infra"


def test_the_agent_marks_a_figure_no_query_returned_and_moves_the_chart(
    page, study_app, monkeypatch
):
    monkeypatch.setattr("lovelaice.agent.agent._build_llm", lambda cfg: Analyst(invent=True))
    url, study = study_app
    _open_study(page, url, study)
    page.wait_for_selector(".log .msg.bot")
    page.fill("#q", QUESTION)
    page.click("#send")
    page.wait_for_selector(".log .foot")
    assert page.locator(".tool.ok").count() == 5
    assert page.locator("mark.unsup").count() == 1
    assert page.locator(".log .foot").inner_text().startswith("1 figure")
    assert page.locator("#chart svg").get_attribute("data-holder") == "border"
    page.reload()
    page.wait_for_selector("mark.unsup")
    assert page.locator(".log .msg.user").inner_text() == QUESTION
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/browser/test_app.py -q -k "study or add_runs or agent"`
Expected: PASS (4 tests).

- [ ] **Step 3: Break it on purpose**

In `study.js`, in the `done` branch of `handle`, replace `mark(b.raw, m.unsupported)` with `mark(b.raw, [])`. Run `uv run pytest tests/browser/test_app.py -q -k marks_a_figure`. Expected: FAIL (no `mark.unsup`). Revert.

- [ ] **Step 4: Commit**

```bash
git add tests/browser/test_app.py
git commit -m "test(browser): the study, its batches and the evaluate agent in Chromium"
```

---

### Task 10: Docs, the spec status, and the acceptance check

**Files:**
- Modify: `README.md`, `AGENTS.md`, `docs/specs/2026-09-29-evaluate-mode-design.md`, `docs/specs/2026-09-28-interface-design.md`, `docs/plans/2026-09-29-casus-app-plan.md`

- [ ] **Step 1: README**

Add rows to the module table: `evaluate/` ("A study's fixed queries, the check on an answer's figures, and the evaluate agent") and `server/study.py` ("Studies by version, batches, and the evaluate agent's chat").

- [ ] **Step 2: AGENTS.md**

Under "What done means", add a check a person runs:

```markdown
- `uv run casus serve`, open a study, **Add runs** (the call count shows before
  anything starts), then **Evaluate** and ask why a quantity never recovers: the
  agent reads the ledger and the rules, the chart follows it, and any figure no
  query returned is marked.
```

- [ ] **Step 3: Spec status and the master plan**

In `docs/specs/2026-09-29-evaluate-mode-design.md` set `status: "implemented in slice 7 (PR #<n>)"`. In `docs/specs/2026-09-28-interface-design.md`, add slice 7 to its status line. In `docs/plans/2026-09-29-casus-app-plan.md`, fill the PR number into slice 7's row and apply the changes listed under "Contract changes needed" below.

- [ ] **Step 4: Acceptance, the way a person does it**

With a real key configured (slice 5's settings screen, or `CASUS_API_KEY_FILE`):

```bash
uv sync
uv run casus run scenarios/smoke --turns 3 --seed 1    # if no smoke study exists yet
uv run casus serve
```

In the browser:

1. The home's second shelf reads **Studies**; the smoke study shows its version, its date and its runs.
2. **Add runs** on it: the confirmation reads `10 × 3 × (2 + 1) = 90 model calls at most · seeds 2–11` (the seeds follow the study's highest). **Start**. The study screen opens; within minutes ten run cards appear one by one, no more than the configured concurrency playing at once (watch `runs/` fill).
3. On the chart, pick a series that only falls in every run. With smoke that is usually Red's supplies: upkeep decays them every turn and only a resupply from Blue raises them. Click the suggestion "Why does … end where it does?", or ask why it never recovers.
4. The answer must come after tool lines that include `ledger` and `read_rules`; the chart must switch to the series the agent talks about; every figure in the answer is either unmarked or marked with the footer count. For each marked figure, say in the PR body whether it was rounding, a difference the model computed, or an invention.
5. Ask "What changes between runs, and what stays the same?": the answer names the number of runs it rests on.
6. Reload the page: the conversation, its tool lines and its marks are back.

Note in the PR body which model answered, the concurrency used, and the counts of marked figures.

- [ ] **Step 5: Journal, commit and open the PR**

Append a `milestone` entry to the workspace journal (`vault/Calendar/Journal/journal-<date>.md`), as the master plan's "After each slice" asks.

```bash
git add README.md AGENTS.md docs/specs/2026-09-29-evaluate-mode-design.md \
  docs/specs/2026-09-28-interface-design.md docs/plans/2026-09-29-casus-app-plan.md
git commit -m "docs: evaluate mode, and how to check it"
git push -u origin 5-slice-7-evaluate-mode
gh pr create --title "feat: evaluate mode, studies by version, batches and the evaluate agent" \
  --body "Part of #5. ..."
```

Use `Fixes #5` instead of `Part of #5` if every other slice has merged by then.

---

## Contract changes needed

> Applied during plan review (2026-09-29) to the master plan's "Amendments from the slice plans" section, resolved against the other slices. Do not edit the master plan again for these; if the code must differ from the amendments, change the amendments in this slice's PR.

The master plan must change in the same PR as this slice, as follows.

1. **File structure, additions.**
   - `src/casus/server/study.py` (the study router), beside slice 6's `server/design.py`. The table says slice 7 "adds routers" to `app.py`; the router lives in its own module and `app.py` only includes it.
   - `tests/evaluate_support.py`, `tests/test_evaluate_{checker,queries,batches,tools,agent}.py`.
2. **File structure, slice 7 modifies files the table assigns to others.**
   - `ui/js/i18n.js` (study strings; the `studies` label becomes "Studies"/"Estudios"), `ui/css/app.css` (study rules, and `#appshell`'s height), `tests/js/harness.js` (one `mark` line), `tests/test_ui_scripts.py`, `tests/test_purity.py` (when slice 6's purity test exists), `pyproject.toml` and `uv.lock` (only if slice 6 has not landed).
3. **Python interfaces, additions.**
   - `studies.Study.to_json()`.
   - `evaluate/queries.py`: `runs(study)`, `read_scenario(study)`, `read_rules(study)`, `render(result) -> str`, `fmt(value) -> str`, `QueryError`. `ledger`'s `run` accepts a run id or a seed.
   - `evaluate/checker.py`: `figures(text) -> list[Figure]`.
   - `server/runs.py`: `batch_plan(scenario, *, n, turns, first_seed) -> dict` with `runs, turns, actors, first_seed, last_seed, calls`. `start_batch` reserves every id through slice 3's `_reserve`, so batch ids are `<name>-<seed>` (with `-2`, `-3`… when taken), the same scheme as a single run.
   - `evaluate/tools.py`: `TOOL_NAMES`, `REFUSED`, `build_tools(study) -> list[AgentTool]`.
   - `evaluate/agent.py`: `build_evaluate_agent(study, settings, session_dir) -> EvaluateAgent` with `async turn(text, send) -> str` and `unsupported() -> list[str]`, mirroring slice 6's `build_design_agent`; `exchanges(messages)`, `history(study, session_dir)`, `session_path(study, session_dir)`. The table names `build_evaluate_agent()` with no signature.
   - `server/study.py`: `router(*, runs_dir, dirs, manager, settings=None)`, `lock_for(scenario, version)`, `session_dir()`.
4. **HTTP.**
   - `GET /studies` items gain `current` (the version is the scenario directory's version now) and `date`.
   - `{scenario}` in every `/studies/...` path is the scenario's name as its transcripts carry it, not a directory name.
   - New: `GET /studies/{scenario}/plan?n=&turns=`, the pre-flight call count the spec requires before a batch starts.
   - New: `GET /studies/{scenario}/{version}/chat` → `{busy, exchanges}`, which restores a study's saved chat with its marks and tells the screen, before anyone types, whether the agent is busy.
   - `POST /studies/{scenario}/runs`: `n` is 1 to 100 (default 10), `turns` optional; 404 when no directory has that scenario name, 422 when it does not validate.
   - `POST /studies/{scenario}/{version}/chat`: 409 while the agent answers on the same study. As in slice 6, an error inside a turn arrives as a `delta` before `done`.
5. **JavaScript.**
   - `Casus.shell.route` handlers receive every remaining path segment: `fn(view, arg, ...rest)`. `#/study/<scenario>/<version>` has two; slice 1's dispatcher passes them all.
   - Home study cards carry `data-study` (the scenario name), `data-version` and `data-current`.
   - `Casus.study = {mark, footer, holders}`.
6. **One chat directory.** Slice 6's `server/design.py` and this slice's `server/study.py` each define the same `session_dir()` (`$XDG_DATA_HOME/casus/sessions`), because neither slice may depend on the other. The master plan should name one home for it (for example `settings.data_dir()`), and the later of the two slices should import it.
7. **The purity test covers both agents.** Whichever of slices 6 and 7 lands second makes `tests/test_purity.py`'s lovelaice test allow `design/{tools,agent}.py` and `evaluate/{tools,agent}.py` and nothing else.
8. **A shared scripted model.** `tests/evaluate_support.Analyst` is shaped like slice 6's `tests/design_support.ScriptedLLM`. Once both are in, the master plan should move the fake model to one `tests/agent_support.py`.

### A note for slice 1 (not a contract change)

Two things in slice 1's plan break this slice's screen or tests as written, and slice 1's implementer may already have met them:

- Playwright's sync API keeps an event loop running on the main thread from the session-scoped `browser` fixture onwards. Any test that calls `engine.run` (and so `asyncio.run`) after the first browser test fails with `RuntimeError: asyncio.run() cannot be called from a running event loop`. That includes slice 1's `run_records` inside browser tests, and every non-browser test that pytest collects after `tests/browser/`. This slice's fixture records on a worker thread; slice 1's helpers need the same, or the browser suite needs its own pytest run.
- `ui/app.html` roots the app in `#appshell`, but the CSS copied from the mockup sizes `#app`, so `#view` has no bounded height. Task 8 adds the `#appshell` rule.
