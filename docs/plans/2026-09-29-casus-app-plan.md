# casus app — master implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn casus from a command line into a local app with a game viewer for live and recorded runs, territorial map regions, a design mode and an evaluate mode.

**Architecture:** One viewer, written as plain browser scripts under `ui/`, consumes transcript records. A FastAPI server (`casus serve`) feeds it from files and, for live runs, from an observer on `engine.run_async` over server-sent events; `casus bundle` inlines the same scripts and the records into one offline HTML file. Map regions are computed once per scenario from Natural Earth data shipped in the package and carried inside the transcript. Design and evaluate are lovelaice agents with fixed tool sets, behind an optional extra.

**Tech Stack:** Python 3.12+, FastAPI + uvicorn, shapely ≥ 2.1, lingo-ai, lovelaice (optional extra, Python 3.13+), plain HTML/CSS/JS with no build step, pytest, Playwright (browser tests in CI).

**Specs:** `docs/specs/2026-09-28-interface-design.md`, `docs/specs/2026-09-29-map-regions-design.md`, `docs/specs/2026-09-29-design-mode-design.md`, `docs/specs/2026-09-29-evaluate-mode-design.md`. Every slice plan argues from these; read the spec before the slice.

This document is the contract between slices. Each slice has its own plan with bite-sized TDD tasks. A slice plan may add private helpers, but it must not rename or change anything this document names without changing this document in the same PR.

---

## Slices

Each slice is one branch from `main`, one PR saying `Part of #5`, merged on green CI before the next branch is cut. Do not stack PRs (a merged base closes the PR built on it). The last slice's PR says `Fixes #5`.

| # | slice | plan | depends on |
|---|---|---|---|
| 1 | The viewer over recordings | `2026-09-29-slice-1-viewer.md` | — |
| 2 | Map regions | `2026-09-29-slice-2-map-regions.md` | 1 |
| 3 | Live runs | `2026-09-29-slice-3-live-runs.md` | 1 |
| 4 | Streaming | `2026-09-29-slice-4-streaming.md` | 3, and a lingo release |
| 5 | Settings | `2026-09-29-slice-5-settings.md` | 1 |
| 6 | Design mode | `2026-09-29-slice-6-design-mode.md` | 2, 5 |
| 7 | Evaluate mode | `2026-09-29-slice-7-evaluate-mode.md` | 3, 5 |

Branch names: `5-slice-N-<slug>`, from `origin/main`, in `.claude/worktrees/`. Run `uv sync --all-extras` in a fresh worktree before any test.

## Global Constraints

- Python floor stays `requires-python = ">=3.12"`. Anything that needs lovelaice lives under the `agents` extra, `lovelaice>=2.13.1; python_version >= '3.13'`, and its tests `pytest.importorskip("lovelaice")`.
- New core dependencies, exactly: `fastapi>=0.115`, `uvicorn>=0.30`, `shapely>=2.1`. Nothing else without changing this line.
- English for every identifier, comment, log line, error string and test name. Words on screen come from the scenario's `display.labels` or from the chrome string table in `ui/js/i18n.js` (`en` and `es`).
- The engine core (`state`, `proxy`, `ruleset`, `resolver`) does no I/O and gains no import from `server`, `geo`, `design`, `evaluate` or `settings`.
- The language model never computes a quantity. Nothing in this plan lets a model output feed a number back into state.
- `casus bundle` output loads nothing from the network: no `http://` or `https://` URL in any `src`, `href` or `url(`. The existing test `test_bundled_html_loads_nothing_from_the_network` keeps guarding it.
- The server binds `127.0.0.1` only. No setting changes that.
- A transcript and a bundle never contain credential material; slice 5 adds the test.
- `ui/` is classic scripts (no `type="module"`), loaded in the fixed order below, each attaching to one global `Casus` namespace. This is so the bundle can concatenate them and so `node --check` means something: it exits 0 on a syntax error in an ES module.
- Line length 96 (ruff). `make test` is the gate and stays the only gate.

## Review Focus

Five inputs the specs imply that no single slice's happy-path tests would meet, most likely first. Each has a test in the slice that owns the code.

1. **A transcript that ends mid-turn** (a crashed or still-running live run): the viewer must show every complete turn and mark the incomplete one, not throw. Owner: slice 1, `test_viewer_truncated_transcript` in the browser suite, and `records.js` unit-tested through it.
2. **A browser that subscribes to a live run after it finished, or reconnects mid-run**: it must receive every record exactly once, in order. Owner: slice 3, `test_late_and_reconnecting_subscribers_get_each_record_once`.
3. **A scenario with no `display` block entries the viewer uses** (no labels, no `card`, no `ladder`, no `lat`/`lon`, no regions): it must still play, with ids for labels and no map rather than a broken one. Owner: slice 1, `test_viewer_plays_a_scenario_with_an_empty_display_block`.
4. **Two places on one base where the seeds are nearly coincident, or a seed exactly on a province border**: region computation must return a finding, never an empty polygon or an exception. Owner: slice 2, `test_near_coincident_seeds_are_a_finding` and `test_seed_on_a_border_belongs_to_one_region`.
5. **The design agent writing a `source` slug with path characters** (`../x`, `a/b`, empty): the write is rejected with a finding and nothing is written outside the scenario directory. Owner: slice 6, `test_slug_with_path_characters_is_refused`.

---

## File structure

What each slice creates or changes. A later slice modifies files an earlier one created only where the table says so.

```
src/casus/
  bundle.py                 1: viewer_records(), new template, script inlining
  display.py                1: actor_label(), place_label(), card(), worse_when_higher()
  engine.py                 3: run_async(observer=...);  4: delta messages
  studies.py                1: RunInfo, list_runs();  7: version_of(), Study, list_studies()
  cli.py                    1: `serve`;  2: `regions`
  scenario.py               2: regions.json merge in Scenario.load, region findings
  stream.py                 4: RationaleReader (incremental JSON reader)
  players.py                4: Player.decide(on_rationale=...)
  settings.py               5: Settings, load/save, apply_to_env, probe
  server/
    __init__.py             1
    app.py                  1: create_app();  3, 5, 6, 7 add routers
    sse.py                  3: event-stream response helper
    runs.py                 3: RunManager;  7: batches
  geo/
    __init__.py             2
    mapdata.py              2: load_admin1(), country(), provinces()
    regions.py              2: compute(), Regions, RegionFinding
  data/admin1.json.xz       2: generated by tools/build_mapdata.py, committed
  design/                   6 (agents extra)
    workspace.py            6: Workspace, WriteResult
    sources.py              6: archive, slugs, cite/assume records
    tools.py                6: build_tools()
    agent.py                6: build_design_agent()
  evaluate/                 7
    queries.py              7: the fixed queries (no lovelaice import)
    checker.py              7: unsupported_numbers() (no lovelaice import)
    tools.py                7: build_tools()  (agents extra)
    agent.py                7: build_evaluate_agent()  (agents extra)
ui/
  app.html                  1: the app shell, loads the scripts in order
  bundle.html               1: the offline template; replaces replay.html
  css/app.css               1
  js/i18n.js                1
  js/records.js             1: RunModel
  js/map.js                 1: dots;  2: regions
  js/card.js                1
  js/viewer.js              1: the four beats;  3: live source;  4: deltas
  js/shell.js               1: home and router;  5: settings;  6: workshop;  7: study
  js/workshop.js            6
  js/study.js               7
  replay.html               1: deleted
tools/build_mapdata.py      2
tests/
  test_bundle.py            1: updated for the new template and ledger records
  test_studies.py           1, 7
  test_server.py            1, 3, 5, 6, 7 add tests
  test_display.py           1: new label and card helpers
  test_regions.py           2
  test_mapdata.py           2
  test_observer.py          3
  test_stream.py            4
  test_settings.py          5
  test_design_*.py          6
  test_evaluate_*.py        7
  browser/                  1: Playwright suite, own CI job
    conftest.py             1: fixtures that build a bundle and start `casus serve`
    test_viewer.py          1, 2, 3, 4
    test_app.py             1, 5, 6, 7
.github/workflows/tests.yml 1: adds the `browser` job
```

Script load order, fixed, in both `app.html` and the bundle: `i18n.js`, `records.js`, `map.js`, `card.js`, `viewer.js`, `shell.js`, then `workshop.js` and `study.js` in the app only.

---

## Contracts

### Records the viewer reads

The viewer reads transcript records unchanged, plus two message kinds that are never written to a transcript:

```json
{"kind": "ledger", "turn": 3, "mutations": 41}
{"kind": "delta", "turn": 3, "actor": "CU", "text": "Reforzar la"}
```

- `ledger` is written by `bundle.viewer_records()` (slice 1) in place of each turn's `mutation` records. The server's `/api/runs/<id>` returns the same list.
- `delta` is sent only over a live event stream (slice 4), one per rationale fragment.

`bundle.viewer_records(records: list[dict]) -> list[dict]` keeps the kinds in `KEPT_KINDS` (`scenario`, `state`, `action`, `event`, `narrative`, `prompt`, `end`, and `error`, which slice 1 adds), drops `mutation` and `declaration`, and inserts one `ledger` record per turn that had mutations, immediately before that turn's next `state` record.

### The scenario record gains regions (slice 2)

The transcript's `scenario` record gains an optional `regions` key holding the contents of `regions.json` as used by the run. `engine.run_async` writes it when the loaded scenario has regions. A viewer that finds no `regions` key draws dots from `lat`/`lon`, as today.

### `regions.json` (slice 2)

```json
{
  "version": 1,
  "mapdata": "ne-10m-admin1-2026-09-29-t0.02",
  "digest": "sha256 of the canonical JSON of every place's region block",
  "theatre": [-86.8, 17.4, -68.2, 29.2],
  "land": [[[[lon, lat], ...]]],
  "places": {
    "cu-habana": {
      "polygon": [[[[lon, lat], ...]]],
      "label": [lon, lat],
      "kind": "provinces"
    }
  },
  "adjacency": {"cu-habana": ["cu-occidente", "cu-centro", "str-florida"]}
}
```

Polygons are GeoJSON MultiPolygon coordinate arrays, rounded to 3 decimals. `kind` is one of `provinces`, `country`, `sea`, `site`. `adjacency` is the computed graph before the YAML's `add`/`remove` exceptions.

### Python interfaces

```python
# display.py (slice 1)
def actor_label(scenario: Scenario, actor_id: str) -> str: ...      # labels[lang][id] or actor name
def place_label(scenario: Scenario, place_id: str) -> str: ...      # labels[lang][id] or place name
def card(scenario: Scenario) -> tuple[str, ...]: ...                # display.card or ()
def worse_when_higher(scenario: Scenario) -> frozenset[str]: ...    # display.worse_when_higher

# studies.py
@dataclass(frozen=True)
class RunInfo:                      # slice 1
    id: str                         # file stem
    path: pathlib.Path
    scenario: str                   # the scenario record's name
    seed: int
    turns_planned: int
    turns_done: int                 # count of state records minus one
    status: Literal["complete", "failed", "incomplete"]
def list_runs(runs_dir: pathlib.Path) -> list[RunInfo]: ...          # slice 1
def version_of(scenario_record: dict) -> str: ...                    # slice 7: 12 hex chars
@dataclass(frozen=True)
class Study:                        # slice 7
    scenario: str
    version: str
    runs: tuple[RunInfo, ...]
def list_studies(runs_dir: pathlib.Path) -> list[Study]: ...          # slice 7

# server/app.py (slice 1)
def create_app(*, scenarios_dir: pathlib.Path, runs_dir: pathlib.Path,
               settings: "Settings | None" = None) -> FastAPI: ...

# engine.py (slice 3)
Observer = Callable[[dict], Awaitable[None]]
async def run_async(scenario, seed=1, out=None, engines=None, narrator_engine=None,
                    turns=None, observer: Observer | None = None) -> RunSummary: ...

# server/runs.py (slice 3)
class RunManager:
    def __init__(self, runs_dir: pathlib.Path, engine_factory=engine_for): ...
    async def start(self, scenario_dir: pathlib.Path, *, seed: int, turns: int | None,
                    model: str | None) -> str: ...                    # returns run id
    def subscribe(self, run_id: str) -> AsyncIterator[dict]: ...      # file so far, then live
    async def start_batch(self, scenario_dir, *, n: int, first_seed: int,
                          turns: int | None, concurrency: int) -> list[str]: ...   # slice 7

# stream.py (slice 4)
class RationaleReader:
    def __init__(self, field: str = "rationale"): ...
    def feed(self, fragment: str) -> str: ...     # returns newly visible characters of the field

# players.py (slice 4)
async def Player.decide(self, world, prompt, offered,
                        on_rationale: Callable[[str], Awaitable[None]] | None = None): ...

# geo/regions.py (slice 2)
@dataclass(frozen=True)
class RegionFinding:
    place: str
    code: str          # e.g. "unknown-province", "seed-outside-base", "empty-region"
    message: str
@dataclass
class Regions:
    places: dict[str, dict]          # as in regions.json
    adjacency: dict[str, list[str]]
    theatre: tuple[float, float, float, float]
    land: list
    findings: list[RegionFinding]
    def to_json(self, digest: str) -> dict: ...
def compute(places: dict[str, dict], display: dict, *, mapdata=None) -> Regions: ...   # mapdata injectable for tests
def region_digest(places: dict[str, dict]) -> str: ...

# settings.py (slice 5)
@dataclass
class Settings:
    endpoint: str
    api_key: str | None
    firecrawl_token: str | None
    player_model: str
    agent_model: str
    run_concurrency: int
    source_dirs: tuple[pathlib.Path, ...]
    origins: dict[str, str]          # field -> "env:NAME" | "config" | "default"
    @classmethod
    def load(cls, path: pathlib.Path | None = None, env: Mapping[str, str] | None = None) -> "Settings": ...
    def save(self, path: pathlib.Path | None = None) -> None: ...
    def public(self) -> dict: ...    # secrets as "configured" / "not set"
    def apply_to_env(self) -> None: ...   # sets BASE_URL / API_KEY for lingo
async def probe(settings: Settings) -> dict: ...   # {"ok", "model", "latency_ms", "error"}

# design/workspace.py (slice 6)
@dataclass(frozen=True)
class WriteResult:
    ok: bool
    findings: tuple[str, ...]
    summary: str
    diff: str
class Workspace:
    def __init__(self, scenario_dir: pathlib.Path): ...
    def read(self, name: Literal["scenario.yaml", "rules.py"]) -> str: ...
    def write(self, name: Literal["scenario.yaml", "rules.py"], text: str) -> WriteResult: ...

# evaluate/queries.py (slice 7)
def series(study: Study, quantity: str, holder: str) -> dict: ...
def finals(study: Study, quantity: str, holder: str) -> dict: ...
def events(study: Study, event_id: str | None = None) -> dict: ...
def ledger(study: Study, ref: str, run: str) -> dict: ...
def choices(study: Study, actor: str | None = None) -> dict: ...
# evaluate/checker.py (slice 7)
def unsupported_numbers(answer: str, tool_results: list[str]) -> list[str]: ...
```

### JavaScript interfaces (slice 1 unless noted)

Defined in full in the slice 1 plan; later slices extend them only as listed.

```js
Casus.i18n.use(lang); Casus.i18n.t(key); Casus.i18n.lang()     // chrome strings, en and es
Casus.records.RunModel          // new RunModel(); .push(record); .onChange(fn(kind, run, record))
  // .header, .scenario, .turns: [{turn, before, after, prompts, actions, events, narrative,
  //   mutations, complete}], .turn(n), .playable(), .deltas[turn][actor] (slice 4 fills it),
  //   .error, .ended
Casus.records.actorIds(run); Casus.records.label(run, key); Casus.records.declarations(turn)
Casus.map.draw(svg, run, snapshot, opts)   // opts: {targets, font, aspect, slice, edges, rscale, ctx}
  // slice 2: draws filled regions when run.scenario.regions exists, dots otherwise
Casus.map.hasMap(run); Casus.map.colour(run, actorId); Casus.map.context(id); Casus.map.esc(s)
Casus.card.html(run, placeId, ctx); Casus.card.attach(document, run); Casus.card.refresh(); Casus.card.fmt(n)
Casus.viewer.mount(root, run, {mode: "live" | "recorded"})   // -> {destroy(), state()}
Casus.viewer.rationaleFor(run, turn, actorId, declared)      // slice 4 makes it read deltas
Casus.shell.start(); Casus.shell.route(name, fn(view, arg) -> teardown?); Casus.shell.onHome(fn(view));
Casus.shell.json(url)
```

Routes: `#/` home, `#/view/<run>` (slice 1), `#/run/<scenario>` (slice 3), `#/design/<scenario>` (slice 6), `#/study/<scenario>/<version>` (slice 7). Home card action rows are `[data-actions="scenario"]` and `[data-actions="study"]`; slices add buttons there through `Casus.shell.onHome`.

### HTTP (all under `/api`)

| method | path | slice | body / response |
|---|---|---|---|
| GET | `/scenarios` | 1 | `[{name, dir, actors, places, turns, valid, findings}]` |
| GET | `/runs` | 1 | `[RunInfo as JSON]` |
| GET | `/runs/{id}` | 1 | `viewer_records(...)` |
| POST | `/runs` | 3 | `{scenario, seed, turns, model}` → `{id}` |
| GET | `/runs/{id}/events` | 3 | `text/event-stream`, one `data: <json>` per record |
| GET | `/studies` | 7 | `[{scenario, version, runs}]` |
| GET | `/studies/{scenario}/{version}/series` | 7 | `?quantity=&holder=` → series table |
| POST | `/studies/{scenario}/runs` | 7 | `{n, turns}` → `{ids}` |
| GET/PUT | `/settings` | 5 | `Settings.public()` / partial update |
| POST | `/settings/probe` | 5 | `probe()` result |
| GET/PUT | `/design/{scenario}/files/{name}` | 6 | draft text / whole-file write → `WriteResult` |
| POST | `/design/{scenario}/chat` | 6 | `{text}` → event stream of agent events |
| POST | `/studies/{scenario}/{version}/chat` | 7 | `{text}` → event stream of agent events |

Agent event stream messages (slices 6, 7): `{"type": "delta", "text"}`, `{"type": "tool_start", "id", "name", "args"}`, `{"type": "tool_end", "id", "ok", "result"}`, `{"type": "done", "unsupported": [...]}` (the last field in slice 7 only).

---

## After each slice

- [ ] `make test` passes locally for the files the slice touched; CI runs the full suite and the browser job.
- [ ] The slice's own acceptance check from its plan, done the way a person would: open the app or the bundle and look.
- [ ] The spec's status header gains the slice number that implemented it; this plan's slice table gains the PR number.
- [ ] Journal entry in the workspace: `commit` and, at the end of a slice, `milestone`.
