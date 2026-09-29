# Slice 2 — map regions

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A place is a territory. `casus regions` builds each place's polygon from Natural Earth
provinces shipped in the package, computes adjacency from shared borders and coasts, and writes
`regions.json`; `Scenario.load` fills adjacency from it; the transcript carries it; the viewer
fills the regions.

**Architecture:** `tools/build_mapdata.py` compacts Natural Earth Admin 1 once into
`src/casus/data/admin1.json.xz`. `casus.geo.mapdata` decodes it; `casus.geo.regions.compute`
turns region blocks into polygons, a theatre, a land outline, adjacency and findings. Only
`casus regions` imports `casus.geo`. `Scenario.load` reads `regions.json` with the standard
library, checks its digest, applies the YAML's `add`/`remove` exceptions and hands the engine a
plain adjacency list, as today. `engine.run_async` writes `regions` into the `scenario` record,
so replay, bundle and the viewer need nothing else. `ui/js/map.js` draws filled regions when
the record carries them, dots otherwise.

**Tech Stack:** Python 3.12, shapely ≥ 2.1 (`coverage_simplify`, `voronoi_polygons(ordered=True)`),
`lzma`, plain JS, pytest, Playwright (slice 1's browser suite).

**Specs:** `docs/specs/2026-09-29-map-regions-design.md` (all of it). Master plan:
`docs/plans/2026-09-29-casus-app-plan.md` (the contracts section is binding). Slice 1:
`docs/plans/2026-09-29-slice-1-viewer.md` (the `map.js`, `card.js` and browser fixtures this
slice extends).

**Measured on 2026-09-29, with the code in this plan run against the real source** (scratch
runs in the workspace playground, `.playground/casus-map/`, not in the repo):

- Build: 4,596 features, 4,501 distinct codes (60 codes span several features and are merged on
  load), 240 countries, 3.1 MB of JSON, 1.065 MB xz, about 15 s. `coverage_is_valid` holds after
  snapping at tolerance 0.02; no province comes out empty.
- Load: 1.6 s to decode; 1.2 s to check coverage validity over the decoded provinces.
- Havana (CU-03) measures 712 km² after compaction against 728 km² in the source. CU, US, DO,
  HT, JM, BS, MX and KY union with no holes; ZA and IT have real ones (Lesotho, San Marino).
- `voronoi_polygons` raises `GEOSException: Multiple input coordinates` on coincident seeds and
  returns cells that do not split the base on seeds 1e-9° apart.
- Natural Earth draws the Guantánamo naval base as its own unit, `-99-X13~`, with no country.
  A `gtmo` site with Oriente as CU-10..CU-14 alone falls on land that is no place, which the spec
  makes a finding. Task 10 adds `-99-X13~` to Oriente.
- The Caribbean, migrated as in Task 10: computed in 0.15 s, no findings, `regions.json` 69 KB,
  four edges differ from the hand-written graph (the table is in Task 10).

## Global Constraints

Everything in the master plan's Global Constraints, plus:

- Running, replaying and bundling need neither shapely nor the map data. Only `casus regions`
  imports `casus.geo.regions` or `casus.geo.mapdata`; `Scenario.load` imports only
  `casus.geo.digest`, which uses the standard library. A test runs a regioned scenario and
  asserts `shapely` never entered `sys.modules`.
- Region computation never raises on scenario input and never emits an empty polygon. Every
  problem is a `RegionFinding`, and a place with a finding gets no polygon.
- `casus regions` writes `regions.json` only when there are no findings. A missing or stale
  `regions.json` makes `Scenario.load` fail, naming the command that fixes it.
- Authors write seeds and sites as `[lat, lon]`. Code and `regions.json` use `[lon, lat]`,
  GeoJSON's order. Convert once, in `regions._lonlat`.
- Tests of region computation use the synthetic `squares()` map data in `tests/test_regions.py`.
  The packaged data is read only by `tests/test_mapdata.py`'s loading tests, one integration test
  in `tests/test_regions.py`, and the two `casus regions` tests in `tests/test_cli.py`, which run
  the command the way a person does.
- Adjacency exceptions apply at both ends: `add: [b]` on `a` also puts `a` in `b`'s list. A plain
  list stays authoritative for its own place only.

## Review Focus

Owned by this slice (from the master plan):

4. Two places on one base with nearly coincident seeds, or a seed exactly on a province border,
   return a finding or a clean split, never an empty polygon or an exception —
   `tests/test_regions.py::test_near_coincident_seeds_are_a_finding` and
   `tests/test_regions.py::test_seed_on_a_border_belongs_to_one_region`.

Also pinned here because this slice owns the code:

- A stale `regions.json` fails the load and names the command —
  `tests/test_scenario.py::test_a_stale_regions_json_fails_with_the_command`.
- A regioned scenario runs, replays and bundles without importing shapely —
  `tests/test_scenario.py::test_loading_and_running_with_regions_never_import_shapely`.
- The home page lists a scenario with a stale map as invalid instead of failing —
  `tests/test_server.py::test_a_scenario_with_a_stale_map_is_listed_invalid_with_the_command`.
- The fill of a region means who holds it; distress stays a gauge —
  `tests/browser/test_viewer.py::test_the_distress_ring_stays_a_gauge_beside_the_label`.
- The v1 reproduction test holds the reference ruleset to v1's map, not the computed one —
  `tests/test_migration.py::test_the_ported_caribbean_reproduces_its_recorded_trajectory`.

Branch: `5-slice-2-map-regions`, from `origin/main` after slice 1 merged, in
`.claude/worktrees/`. Run `uv sync --all-extras` first.

---

### Task 1: The shapely dependency and the map data tool

**Files:**
- Modify: `pyproject.toml`, `uv.lock`
- Create: `tools/build_mapdata.py`
- Test: `tests/test_mapdata.py`

**Interfaces:**
- Produces (in the tool, loaded by path in tests, never imported by the package):
  `SCALE = 1000`, `TOLERANCE = 0.02`, `GRID = 0.001`, `class CoverageInvalid(RuntimeError)`,
  `compact(geoms: list, tolerance=TOLERANCE, grid=GRID) -> list`,
  `encode(code: str, name: str, country: str, geom) -> list` returning
  `[code, name, country, polygons]` where each polygon is a list of rings (exterior first, then
  holes) and each ring is `[x0, y0, dx1, dy1, ...]` in thousandths of a degree.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add `"shapely>=2.1",` to `dependencies`, keeping the list sorted:

```toml
dependencies = [
    "fastapi>=0.115",
    "httpx>=0.27",
    "lingo-ai>=2.1.0",
    "pydantic>=2.7",
    "pyyaml>=6.0",
    "shapely>=2.1",
    "uvicorn>=0.30",
]
```

Run: `uv lock && uv sync --all-extras`
Expected: `shapely==2.1.x` in the resolved set.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_mapdata.py`:

```python
"""The map data shipped in the package, and the one-shot tool that builds it."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest
import shapely
from shapely.geometry import box

ROOT = pathlib.Path(__file__).parent.parent
TOOL = ROOT / "tools" / "build_mapdata.py"


def _tool():
    """The tool is not part of the package, so the tests load it by path."""
    spec = importlib.util.spec_from_file_location("build_mapdata", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_tool_keeps_a_valid_coverage_valid():
    compacted = _tool().compact([box(0, 0, 1, 1), box(1, 0, 2, 1)])
    assert len(compacted) == 2
    assert shapely.coverage_is_valid(compacted)


def test_the_tool_fails_when_the_coverage_does_not_hold():
    tool = _tool()
    with pytest.raises(tool.CoverageInvalid, match="raise the tolerance"):
        tool.compact([box(0, 0, 2, 2), box(1, 0, 3, 2)])


def test_a_ring_is_stored_as_integer_steps_from_its_first_point():
    code, name, country, [[ring]] = _tool().encode("AA-1", "One", "AA", box(0, 0, 0.5, 0.25))
    assert (code, name, country) == ("AA-1", "One", "AA")
    assert all(isinstance(v, int) for v in ring)
    x, y = ring[0], ring[1]
    for dx, dy in zip(ring[2::2], ring[3::2], strict=True):
        x, y = x + dx, y + dy
    assert (x, y) == (ring[0], ring[1]), "the ring does not close"
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_mapdata.py -q`
Expected: FAIL with `FileNotFoundError: [Errno 2] No such file or directory: '.../tools/build_mapdata.py'`.

- [ ] **Step 4: Implement `tools/build_mapdata.py`**

```python
#!/usr/bin/env python3
"""Turn Natural Earth Admin 1 into `src/casus/data/admin1.json.xz`.

A one-shot generator. Its output is committed; nothing imports this file. Run it
again only to change the source or the tolerance.

    mkdir -p .cache && curl -sL -o .cache/ne_10m_admin_1.geojson \\
      https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson
    uv run python tools/build_mapdata.py

Source: Natural Earth, Admin 1 States and Provinces at 1:10m, public domain.

Four steps, measured on 2026-09-29 (docs/specs/2026-09-29-map-regions-design.md):
simplify the whole coverage at once, so each shared border moves once; snap to a
0.001° grid; store integers, delta-encoded per ring; compress with xz. The tool
fails if the coverage is not valid after snapping, because a gap or an overlap
between provinces would become a gap or an overlap between regions.
"""

from __future__ import annotations

import argparse
import datetime
import json
import lzma
import pathlib
import sys

import shapely
from shapely.geometry import shape

#: Degrees, about 2 km. At 0.01 the coverage does not stay valid after snapping.
TOLERANCE = 0.02

#: Degrees, about 100 m. Coordinates are stored as integers in these units.
GRID = 0.001
SCALE = 1000


class CoverageInvalid(RuntimeError):
    """Simplifying or snapping opened a gap or an overlap between provinces."""


def compact(geoms: list, tolerance: float = TOLERANCE, grid: float = GRID) -> list:
    """Simplify the coverage in one pass and snap it to the grid. Fails if the
    result is no longer a coverage."""
    simplified = shapely.coverage_simplify(geoms, tolerance=tolerance)
    snapped = shapely.set_precision(simplified, grid)
    if not bool(shapely.coverage_is_valid(snapped)):
        raise CoverageInvalid(
            f"the coverage is not valid after simplifying at {tolerance} and snapping "
            f"to {grid}; raise the tolerance"
        )
    return list(snapped)


def encode(code: str, name: str, country: str, geom) -> list:
    """One province: its polygons, each a list of rings (exterior first), each ring
    its first point and then the integer steps to every following point."""
    polygons = []
    for polygon in shapely.get_parts(geom):
        rings = []
        for ring in (polygon.exterior, *polygon.interiors):
            points = [(round(x * SCALE), round(y * SCALE)) for x, y in ring.coords]
            steps = [*points[0]]
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                if (x1, y1) != (x0, y0):
                    steps += [x1 - x0, y1 - y0]
            rings.append(steps)
        polygons.append(rings)
    return [code, name, country, polygons]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=".cache/ne_10m_admin_1.geojson")
    parser.add_argument("--out", default="src/casus/data/admin1.json.xz")
    parser.add_argument("--tolerance", type=float, default=TOLERANCE)
    args = parser.parse_args()

    features = json.loads(pathlib.Path(args.source).read_text())["features"]
    geoms = [shapely.make_valid(shape(f["geometry"])) for f in features]
    try:
        snapped = compact(geoms, args.tolerance)
    except CoverageInvalid as exc:
        print(f"build_mapdata: {exc}", file=sys.stderr)
        return 1

    countries: dict[str, str] = {}
    provinces = []
    for feature, geom in zip(features, snapped, strict=True):
        props = feature["properties"]
        # Natural Earth writes -1 for disputed units that belong to no country.
        country = "" if props["iso_a2"] == "-1" else props["iso_a2"]
        if country:
            countries.setdefault(country, props["admin"])
        provinces.append(encode(props["iso_3166_2"], props["name"], country, geom))

    today = datetime.date.today().isoformat()
    payload = {
        "version": f"ne-10m-admin1-{today}-t{args.tolerance}",
        "source": "Natural Earth Admin 1 States and Provinces 1:10m (public domain)",
        "tolerance": args.tolerance,
        "scale": SCALE,
        "countries": dict(sorted(countries.items())),
        "provinces": provinces,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(lzma.compress(raw, preset=9))
    codes = len({p[0] for p in provinces})
    size = out.stat().st_size / 1e6
    print(
        f"wrote {out} — {len(provinces)} features, {codes} codes, "
        f"{len(countries)} countries, {size:.2f} MB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_mapdata.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock tools/build_mapdata.py tests/test_mapdata.py
git commit -m "feat(tools): build the packaged province map from Natural Earth"
```

---

### Task 2: The packaged map data and its loader

**Files:**
- Create: `src/casus/geo/__init__.py`, `src/casus/geo/mapdata.py`
- Create (generated, committed): `src/casus/data/admin1.json.xz`
- Test: `tests/test_mapdata.py`

**Interfaces:**
- Consumes: the payload `tools/build_mapdata.py` writes: `{version, source, tolerance, scale,
  countries: {alpha2: name}, provinces: [[code, name, alpha2, polygons], ...]}`.
- Produces:
  - `MapData(version, geoms, names, country_of, countries)`, frozen, with
    `.country(code) -> BaseGeometry` (the union of its provinces, cached) and
    `.land(bounds) -> BaseGeometry` (every province inside `(lon0, lat0, lon1, lat1)`, merged,
    clipped to it).
  - `decode(payload: dict) -> MapData`
  - `load_admin1(path: pathlib.Path = DATA) -> MapData`, cached per process.
  - `provinces(codes: Iterable[str], data: MapData | None = None) -> BaseGeometry`
  - `country(code: str, data: MapData | None = None) -> BaseGeometry`

- [ ] **Step 1: Write the failing tests**

In `tests/test_mapdata.py`, add `import math` to the standard-library imports and
`from casus.geo import mapdata` after the third-party imports. Append:

```python
def _payload(*provinces, countries=None) -> dict:
    tool = _tool()
    return {
        "version": "test",
        "scale": tool.SCALE,
        "countries": countries or {"AA": "Alpha"},
        "provinces": [tool.encode(*p) for p in provinces],
    }


def test_a_province_decodes_to_the_polygon_that_was_encoded():
    shape = shapely.Polygon([(0, 0), (2, 0), (2, 2), (0, 2)], [[(0.5, 0.5), (1, 0.5), (1, 1)]])
    decoded = mapdata.decode(_payload(("AA-1", "One", "AA", shape)))
    assert decoded.geoms["AA-1"].equals(shape)
    assert decoded.names["AA-1"] == "One"


def test_a_code_split_over_two_features_is_one_province():
    decoded = mapdata.decode(
        _payload(("AA-1", "One", "AA", box(0, 0, 1, 1)), ("AA-1", "One", "AA", box(1, 0, 2, 1)))
    )
    assert decoded.geoms["AA-1"].geom_type == "Polygon"
    assert decoded.geoms["AA-1"].area == pytest.approx(2.0)


def test_a_country_is_the_union_of_its_provinces():
    decoded = mapdata.decode(
        _payload(
            ("AA-1", "One", "AA", box(0, 0, 1, 1)),
            ("AA-2", "Two", "AA", box(1, 0, 2, 1)),
            ("BB-1", "Three", "BB", box(2, 0, 3, 1)),
            countries={"AA": "Alpha", "BB": "Beta"},
        )
    )
    assert mapdata.country("AA", decoded).equals(box(0, 0, 2, 1))
    assert mapdata.provinces(["AA-2", "BB-1"], decoded).equals(box(1, 0, 3, 1))


def test_the_land_inside_a_box_is_every_province_there_clipped_to_it():
    decoded = mapdata.decode(
        _payload(("AA-1", "One", "AA", box(0, 0, 1, 1)), ("AA-2", "Two", "AA", box(1, 0, 2, 1)))
    )
    assert decoded.land((0.5, 0.0, 3.0, 1.0)).equals(box(0.5, 0, 2, 1))


# --- the packaged data ---------------------------------------------------------


def test_the_packaged_data_names_its_version_and_is_decoded_once():
    data = mapdata.load_admin1()
    assert data.version.startswith("ne-10m-admin1-") and data.version.endswith("-t0.02")
    assert len(data.geoms) > 4000
    assert data is mapdata.load_admin1()


def test_the_packaged_coverage_is_valid():
    """No gap and no overlap between provinces, or the regions built from them
    would have one too."""
    assert shapely.coverage_is_valid(list(mapdata.load_admin1().geoms.values()))


@pytest.mark.parametrize("code", ["CU-03", "CU-16", "US-FL", "US-PR"])
def test_a_packaged_province_is_a_valid_polygon(code):
    shape = mapdata.provinces([code])
    assert shape.is_valid and not shape.is_empty


@pytest.mark.parametrize("code", ["CU", "US", "DO", "HT", "JM", "BS", "MX"])
def test_a_packaged_country_union_has_no_holes(code):
    shape = mapdata.country(code)
    assert shape.is_valid and not shape.is_empty
    assert sum(len(p.interiors) for p in shapely.get_parts(shape)) == 0


def test_havana_keeps_close_to_its_source_area():
    """Ciudad de la Habana is 728 km² in the source; 712 km² after compaction was
    measured on 2026-09-29."""
    shape = mapdata.provinces(["CU-03"])
    km2 = shape.area * 111.32**2 * math.cos(math.radians(23.1))
    assert 690 < km2 < 740
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_mapdata.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'casus.geo'`.

- [ ] **Step 3: Implement `src/casus/geo/__init__.py` and `src/casus/geo/mapdata.py`**

`src/casus/geo/__init__.py`, one line and nothing else, so that importing `casus.geo.digest`
from `Scenario.load` imports no shapely:

```python
"""Places as territory: the packaged map data, region computation, the digest."""
```

`src/casus/geo/mapdata.py`:

```python
"""The map data shipped in the package: Natural Earth Admin 1 (states and
provinces) at 1:10m, compacted by `tools/build_mapdata.py` into
`data/admin1.json.xz`.

A country is not stored. It is the union of its provinces by Natural Earth's
`iso_a2`, which is not always the prefix of the province code (`US-PR` belongs to
`PR`). Only computing regions reads this module; running, replaying and bundling
a scenario never import it.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import lzma
import pathlib
from collections.abc import Iterable

import shapely
from shapely.geometry.base import BaseGeometry

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "admin1.json.xz"


@dataclasses.dataclass(frozen=True)
class MapData:
    version: str
    geoms: dict[str, BaseGeometry]  # ISO 3166-2 code -> its polygon
    names: dict[str, str]  # ISO 3166-2 code -> its name
    country_of: dict[str, str]  # ISO 3166-2 code -> ISO 3166-1 alpha-2, "" for none
    countries: dict[str, str]  # ISO 3166-1 alpha-2 -> its name
    _cache: dict = dataclasses.field(default_factory=dict, compare=False, repr=False)

    def country(self, code: str) -> BaseGeometry:
        """The union of a country's provinces, computed once."""
        if code not in self.countries:
            raise KeyError(code)
        key = ("country", code)
        if key not in self._cache:
            parts = [g for c, g in sorted(self.geoms.items()) if self.country_of[c] == code]
            self._cache[key] = shapely.union_all(parts)
        return self._cache[key]

    def land(self, bounds: tuple[float, float, float, float]) -> BaseGeometry:
        """Every province inside `bounds` (lon0, lat0, lon1, lat1), merged and
        clipped: the outline a theatre draws for context."""
        if "tree" not in self._cache:
            codes = sorted(self.geoms)
            self._cache["tree"] = (codes, shapely.STRtree([self.geoms[c] for c in codes]))
        codes, tree = self._cache["tree"]
        frame = shapely.box(*bounds)
        hits = [self.geoms[codes[i]] for i in sorted(tree.query(frame))]
        return shapely.union_all(hits).intersection(frame) if hits else shapely.Polygon()


def _ring(steps: list[int], scale: int) -> list[tuple[float, float]]:
    x, y = steps[0], steps[1]
    points = [(x / scale, y / scale)]
    for i in range(2, len(steps), 2):
        x += steps[i]
        y += steps[i + 1]
        points.append((x / scale, y / scale))
    return points


def _geometry(polygons: list, scale: int) -> BaseGeometry:
    parts = [
        shapely.Polygon(_ring(rings[0], scale), [_ring(r, scale) for r in rings[1:]])
        for rings in polygons
    ]
    return parts[0] if len(parts) == 1 else shapely.MultiPolygon(parts)


def decode(payload: dict) -> MapData:
    """The compact payload as shapely geometries. A code that Natural Earth
    splits over several features becomes one province."""
    scale = int(payload["scale"])
    parts: dict[str, list[BaseGeometry]] = {}
    names: dict[str, str] = {}
    country_of: dict[str, str] = {}
    for code, name, country, polygons in payload["provinces"]:
        parts.setdefault(code, []).append(_geometry(polygons, scale))
        names.setdefault(code, name)
        country_of[code] = country
    geoms = {c: g[0] if len(g) == 1 else shapely.union_all(g) for c, g in parts.items()}
    return MapData(
        version=str(payload["version"]),
        geoms=geoms,
        names=names,
        country_of=country_of,
        countries=dict(payload["countries"]),
    )


@functools.lru_cache(maxsize=4)
def load_admin1(path: pathlib.Path = DATA) -> MapData:
    """The packaged map data, decoded once per process (about 1.6 s)."""
    return decode(json.loads(lzma.decompress(path.read_bytes())))


def provinces(codes: Iterable[str], data: MapData | None = None) -> BaseGeometry:
    """The union of the named provinces. An unknown code raises KeyError."""
    data = data if data is not None else load_admin1()
    return shapely.union_all([data.geoms[c] for c in codes])


def country(code: str, data: MapData | None = None) -> BaseGeometry:
    """A whole country. An unknown code raises KeyError."""
    return (data if data is not None else load_admin1()).country(code)
```

- [ ] **Step 4: Generate the packaged data**

```bash
mkdir -p .cache && curl -sL -o .cache/ne_10m_admin_1.geojson \
  https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson
uv run python tools/build_mapdata.py
```

Expected (about 15 s): `wrote src/casus/data/admin1.json.xz — 4596 features, 4501 codes, 240
countries, 1.06 MB` (the last figure may read 1.07). If the tool exits 1 with `the coverage is
not valid`, the source changed upstream; stop and report it rather than raising the tolerance.

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_mapdata.py -q`
Expected: PASS (all tests, 3 from Task 1 and the new ones).

- [ ] **Step 6: Check the wheel carries the data**

`[tool.hatch.build.targets.wheel] packages = ["src/casus"]` ships every file under the package
that git does not ignore, so no configuration changes. Check it on the artifact:

```bash
uv build --wheel --out-dir /tmp/casus-wheel
uv run python -c "import glob, zipfile; w = glob.glob('/tmp/casus-wheel/casus-*.whl')[0]; names = zipfile.ZipFile(w).namelist(); assert 'casus/data/admin1.json.xz' in names, names; print('ok', w)"
```

Expected: `ok /tmp/casus-wheel/casus-0.1.0-py3-none-any.whl`, exit code 0.

- [ ] **Step 7: Commit**

```bash
git add src/casus/geo/__init__.py src/casus/geo/mapdata.py src/casus/data/admin1.json.xz \
  tests/test_mapdata.py
git commit -m "feat(geo): ship Natural Earth provinces in the package, and load them"
```

---

### Task 3: Regions of every kind

**Files:**
- Create: `src/casus/geo/digest.py`, `src/casus/geo/regions.py`
- Test: `tests/test_regions.py`

**Interfaces:**
- Consumes: `mapdata.MapData`, `mapdata.load_admin1()`, `mapdata.provinces(codes, data)`,
  `MapData.country(code)`, `MapData.land(bounds)`.
- Produces (master plan names, exactly): `RegionFinding(place, code, message)`,
  `Regions(places, adjacency, theatre, land, findings, mapdata="")` with `.to_json(digest)`,
  `compute(places: dict[str, dict], display: dict, *, mapdata=None) -> Regions`,
  `region_digest(places: dict[str, dict], theatre: list[float] | None = None) -> str`
  (defined in `geo/digest.py`, re-exported from `geo/regions.py`). Module constants the tests
  bind to: `VERSION`, `KM_PER_DEGREE`, `DEFAULT_REACH_KM`, `DEFAULT_RADIUS_KM`, `MIN_BORDER_KM`,
  `MIN_SEED_KM`, `MARGIN_DEGREES`, `DECIMALS`.
- In this task `compute` returns every place with an empty adjacency list; Task 5 computes it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_regions.py`:

```python
"""Regions from region blocks, on a small synthetic coverage so no test depends
on real borders. One test at the end reads the packaged data."""

from __future__ import annotations

import json
import math

import pytest
import shapely
from shapely.geometry import Point, box, shape

from casus.geo import regions
from casus.geo.mapdata import MapData
from casus.geo.regions import compute, region_digest

#: Five 2° squares near the equator. AA-1..AA-4 are a 2×2 block, country AA; BB-1
#: lies east of AA-2, country BB, and touches AA-4 only at the corner (4, 2).
#: Everything else in the theatre is water.
CELLS = {
    "AA-1": box(0, 0, 2, 2),
    "AA-2": box(2, 0, 4, 2),
    "AA-3": box(0, 2, 2, 4),
    "AA-4": box(2, 2, 4, 4),
    "BB-1": box(4, 0, 6, 2),
}
THEATRE = {"theatre": [-2, -2, 8, 6]}


def squares() -> MapData:
    return MapData(
        version="squares",
        geoms=dict(CELLS),
        names={code: f"Square {code}" for code in CELLS},
        country_of={code: code[:2] for code in CELLS},
        countries={"AA": "Alpha", "BB": "Beta"},
    )


def _compute(places: dict, display: dict | None = None) -> regions.Regions:
    return compute(places, THEATRE if display is None else display, mapdata=squares())


def _shape(result: regions.Regions, place: str):
    return shape({"type": "MultiPolygon", "coordinates": result.places[place]["polygon"]})


def _km2(geom) -> float:
    lat = math.radians(geom.centroid.y)
    return geom.area * regions.KM_PER_DEGREE**2 * math.cos(lat)


def test_a_place_on_provinces_takes_their_union():
    result = _compute({"west": {"region": {"provinces": ["AA-1", "AA-3"]}}})
    assert result.findings == []
    assert _shape(result, "west").equals(box(0, 0, 2, 4))
    assert result.places["west"]["kind"] == "provinces"


def test_two_places_on_one_province_split_it_between_their_seeds():
    result = _compute(
        {
            "west": {"region": {"provinces": ["AA-1"], "seed": [1.0, 0.5]}},
            "east": {"region": {"provinces": ["AA-1"], "seed": [1.0, 1.5]}},
        }
    )
    assert result.findings == []
    assert _shape(result, "west").equals(box(0, 0, 1, 2))
    assert _shape(result, "east").equals(box(1, 0, 2, 2))
    assert result.places["west"]["label"] == [0.5, 1.0]


def test_a_place_on_a_country_takes_all_of_it():
    result = _compute({"alpha": {"region": {"country": "AA"}}})
    assert _shape(result, "alpha").equals(box(0, 0, 4, 4))
    assert result.places["alpha"]["kind"] == "country"


def test_two_places_on_one_country_split_it_without_overlap():
    result = _compute(
        {
            "south": {"region": {"country": "AA", "seed": [1.0, 1.0]}},
            "north": {"region": {"country": "AA", "seed": [3.0, 3.0]}},
        }
    )
    south, north = _shape(result, "south"), _shape(result, "north")
    assert south.area == pytest.approx(8.0) and north.area == pytest.approx(8.0)
    assert south.intersection(north).area == pytest.approx(0.0)
    assert south.union(north).equals(box(0, 0, 4, 4))


def test_the_same_provinces_in_another_order_are_the_same_base():
    result = _compute(
        {
            "a": {"region": {"provinces": ["AA-1", "AA-2"], "seed": [1.0, 1.0]}},
            "b": {"region": {"provinces": ["AA-2", "AA-1"], "seed": [1.0, 3.0]}},
        }
    )
    assert result.findings == []
    assert _shape(result, "a").equals(box(0, 0, 2, 2))


def test_a_sea_zone_is_water_cut_to_its_reach():
    result = _compute({"gulf": {"region": {"sea": [1.0, -1.0], "reach_km": 50}}})
    gulf = _shape(result, "gulf")
    assert result.places["gulf"]["kind"] == "sea"
    assert gulf.intersection(box(0, 0, 6, 4)).area == pytest.approx(0.0)
    assert _km2(gulf) == pytest.approx(math.pi * 50**2, rel=0.02)
    assert result.places["gulf"]["label"] == [-1.0, 1.0]


def test_two_sea_zones_split_the_water_between_them():
    result = _compute(
        {
            "west": {"region": {"sea": [1.0, -1.0], "reach_km": 600}},
            "east": {"region": {"sea": [1.0, 7.0], "reach_km": 600}},
        }
    )
    west, east = _shape(result, "west"), _shape(result, "east")
    assert west.intersection(east).area == pytest.approx(0.0)
    assert west.bounds[2] == pytest.approx(3.0) and east.bounds[0] == pytest.approx(3.0)


def test_a_site_is_a_disc_carved_out_of_the_region_it_sits_in():
    result = _compute(
        {
            "land": {"region": {"provinces": ["AA-1"]}},
            "base": {"region": {"site": [1.0, 1.0], "radius_km": 20}},
        }
    )
    assert result.findings == []
    base, land = _shape(result, "base"), _shape(result, "land")
    assert result.places["base"]["kind"] == "site"
    assert _km2(base) == pytest.approx(math.pi * 20**2, rel=0.02)
    assert not land.contains(Point(1.0, 1.0))
    assert land.area == pytest.approx(4.0 - base.area, rel=1e-3)


def test_a_site_without_a_radius_takes_the_default():
    result = _compute({"base": {"region": {"site": [1.0, -1.0]}}})
    radius = regions.DEFAULT_RADIUS_KM
    assert _km2(_shape(result, "base")) == pytest.approx(math.pi * radius**2, rel=0.02)


def test_a_label_point_lies_inside_its_region():
    result = _compute({"ell": {"region": {"provinces": ["AA-1", "AA-2", "AA-4"]}}})
    assert _shape(result, "ell").contains(Point(result.places["ell"]["label"]))


def test_the_theatre_is_the_bounding_box_of_every_region_with_a_margin():
    result = compute({"west": {"region": {"provinces": ["AA-1"]}}}, {}, mapdata=squares())
    m = regions.MARGIN_DEGREES
    assert result.theatre == (-m, -m, 2 + m, 2 + m)


def test_the_scenario_can_set_the_theatre():
    result = _compute({"west": {"region": {"provinces": ["AA-1"]}}})
    assert result.theatre == (-2.0, -2.0, 8.0, 6.0)


def test_the_land_outline_is_every_province_in_the_theatre_clipped_to_it():
    """BB-1 is no place and is still drawn: land for context."""
    result = _compute({"west": {"region": {"provinces": ["AA-1"]}}}, {"theatre": [1, 1, 5, 3]})
    land = shape({"type": "MultiPolygon", "coordinates": result.land})
    assert land.bounds == (1.0, 1.0, 5.0, 3.0)
    assert land.area == pytest.approx(7.0)
    assert _shape(result, "west").equals(box(1, 1, 2, 2))


def test_regions_json_has_the_shape_the_viewer_reads():
    result = _compute(
        {
            "west": {"region": {"provinces": ["AA-1"]}},
            "gulf": {"region": {"sea": [1.0, -1.0], "reach_km": 50}},
        }
    )
    doc = result.to_json("abc")
    keys = {"version", "mapdata", "digest", "theatre", "land", "places", "adjacency"}
    assert set(doc) == keys
    assert (doc["version"], doc["mapdata"]) == (regions.VERSION, "squares")
    assert doc["digest"] == "abc"
    assert set(doc["places"]["west"]) == {"polygon", "label", "kind"}
    assert all(type(v) is float for v in doc["theatre"])
    coords = shapely.get_coordinates(_shape(result, "gulf")).flatten()
    assert all(round(v, regions.DECIMALS) == v for v in coords)
    json.dumps(doc)


def test_the_digest_follows_the_region_blocks_and_the_theatre_only():
    places = {"a": {"name": "A", "region": {"provinces": ["AA-1"]}}, "b": {"name": "B"}}
    reordered = {"b": {"name": "Renamed"}, "a": {"region": {"provinces": ["AA-1"]}}}
    assert region_digest(places) == region_digest(reordered)
    moved = {**places, "a": {"region": {"provinces": ["AA-2"]}}}
    assert region_digest(moved) != region_digest(places)
    assert region_digest(places, [0, 0, 1, 1]) != region_digest(places)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_regions.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'casus.geo.regions'`.

- [ ] **Step 3: Implement `src/casus/geo/digest.py`**

```python
"""The digest that ties a scenario's regions.json to the blocks it was computed
from. It lives apart from regions.py so that loading a scenario never imports
shapely."""

from __future__ import annotations

import hashlib
import json


def region_digest(places: dict[str, dict], theatre: list[float] | None = None) -> str:
    """sha256 of the canonical JSON of every place's region block and of the
    theatre the scenario sets: the two inputs the geometry depends on."""
    blocks = {
        place_id: spec["region"]
        for place_id, spec in places.items()
        if isinstance(spec, dict) and "region" in spec
    }
    canonical = json.dumps(
        {"places": blocks, "theatre": theatre},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
```

- [ ] **Step 4: Implement `src/casus/geo/regions.py`**

```python
"""Places as territory: a polygon per place, computed once from the map data.

The base of a place is the union of the provinces it names, a whole country, or
the sea inside the theatre. Places on the same base split it by Voronoi among
their seeds; a place alone on its base takes all of it. A site is a disc carved
out of whatever it sits in. A sea zone is a sea place cut to a reach around its
seed, so a few zones do not claim a whole ocean.

Authors write seeds and sites as [lat, lon]. Inside this module and in
regions.json every coordinate is [lon, lat], GeoJSON's order.

Only `casus regions` runs this. A problem in a region block comes back as a
finding, never as an exception or an empty polygon: a place with a finding gets
no polygon at all.
"""

from __future__ import annotations

import dataclasses
import difflib
import math

import shapely
from shapely import affinity
from shapely.errors import GEOSException
from shapely.geometry import MultiPoint, Point, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import polylabel

from . import mapdata as mapdata_mod
from .digest import region_digest

__all__ = ["RegionFinding", "Regions", "compute", "region_digest"]

#: The regions.json format.
VERSION = 1
KM_PER_DEGREE = 111.32
#: A sea zone's reach and a site's radius when the block does not give one.
DEFAULT_REACH_KM = 240.0
DEFAULT_RADIUS_KM = 15.0
#: Two regions are neighbours when they share more border than this.
MIN_BORDER_KM = 1.0
#: Seeds closer than this cannot split a base. GEOS raises on coincident seeds and
#: returns cells that mean nothing for nearly coincident ones.
MIN_SEED_KM = 1.0
#: Added on every side of the regions' bounding box when the scenario sets no theatre.
MARGIN_DEGREES = 1.0
#: regions.json rounds to 0.001°, about 100 m, the grid the map data is snapped to.
DECIMALS = 3
GRID = 10.0**-DECIMALS
KINDS = ("provinces", "country", "sea", "site")


@dataclasses.dataclass(frozen=True)
class RegionFinding:
    place: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.place}: {self.code}: {self.message}"


@dataclasses.dataclass
class Regions:
    places: dict[str, dict]
    adjacency: dict[str, list[str]]
    theatre: tuple[float, float, float, float]
    land: list
    findings: list[RegionFinding]
    #: The map data version the regions were built from.
    mapdata: str = ""

    def to_json(self, digest: str) -> dict:
        return {
            "version": VERSION,
            "mapdata": self.mapdata,
            "digest": digest,
            "theatre": list(self.theatre),
            "land": self.land,
            "places": self.places,
            "adjacency": self.adjacency,
        }


@dataclasses.dataclass(frozen=True)
class _Spec:
    kind: str
    base: tuple[str, ...]  # what places share to split it: ("provinces", *codes), ...
    seed: tuple[float, float] | None  # (lon, lat)
    size_km: float = 0.0  # a sea zone's reach or a site's radius


# --- measuring ---------------------------------------------------------------


def _local(geom: BaseGeometry, lat: float) -> BaseGeometry:
    """The geometry in kilometres, equirectangular around `lat`: good to a
    kilometre across a theatre, which is all a border threshold needs."""
    return affinity.scale(
        geom,
        xfact=KM_PER_DEGREE * math.cos(math.radians(lat)),
        yfact=KM_PER_DEGREE,
        origin=(0, 0),
    )


def _km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * math.cos(lat), a[1] - b[1]) * KM_PER_DEGREE


def _disc(centre: tuple[float, float], radius_km: float) -> BaseGeometry:
    """A circle on the ground, which in degrees is an ellipse wider than tall."""
    lon, lat = centre
    circle = Point(lon, lat).buffer(radius_km / KM_PER_DEGREE, quad_segs=16)
    stretch = 1 / max(math.cos(math.radians(lat)), 0.01)
    return affinity.scale(circle, xfact=stretch, yfact=1.0, origin=(lon, lat))


def _polygonal(geom: BaseGeometry) -> BaseGeometry:
    """Only the areas: an intersection along a shared edge also leaves lines."""
    polygons = [
        part
        for piece in shapely.get_parts(geom)
        for part in shapely.get_parts(piece)
        if part.geom_type == "Polygon" and not part.is_empty
    ]
    return shapely.union_all(polygons) if polygons else shapely.Polygon()


# --- reading region blocks ---------------------------------------------------


def _province_hint(code: str, data: mapdata_mod.MapData) -> str:
    """The codes the author may have meant, with their names: the provinces of the
    same country when the prefix names one, else the closest codes."""
    prefix = code.split("-", 1)[0] + "-"
    same = sorted(c for c in data.geoms if c.startswith(prefix))
    if not same:
        same = difflib.get_close_matches(code, sorted(data.geoms), n=3, cutoff=0.5)
    shown = ", ".join(f"{c} ({data.names[c]})" for c in same[:12])
    more = f" and {len(same) - 12} more" if len(same) > 12 else ""
    return f"did you mean {shown or 'none'}{more}"


def _country_hint(code: str, data: mapdata_mod.MapData) -> str:
    named = [c for c, name in sorted(data.countries.items()) if code.lower() in name.lower()]
    near = difflib.get_close_matches(code.upper(), sorted(data.countries), n=3, cutoff=0.5)
    found = list(dict.fromkeys(named + near))[:5]
    return "did you mean " + (", ".join(f"{c} ({data.countries[c]})" for c in found) or "none")


def _lonlat(place: str, value: object, findings: list) -> tuple[float, float] | None:
    """An author's [lat, lon] as (lon, lat), or a finding."""
    numbers = (
        isinstance(value, list | tuple)
        and len(value) == 2
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
    )
    if not numbers or not (-90 <= value[0] <= 90 and -180 <= value[1] <= 180):
        message = f"{value!r} is not a [lat, lon] pair"
        findings.append(RegionFinding(place, "bad-region", message))
        return None
    return float(value[1]), float(value[0])


def _km_value(place: str, block: dict, key: str, default: float, findings: list):
    value = block.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        findings.append(
            RegionFinding(
                place, "bad-region", f"{key} must be a positive number of km, not {value!r}"
            )
        )
        return None
    return float(value)


def _parse(place: str, block: object, data: mapdata_mod.MapData, findings: list):
    kinds = [k for k in KINDS if k in block] if isinstance(block, dict) else []
    if len(kinds) != 1:
        findings.append(
            RegionFinding(
                place, "bad-region", "a region block names exactly one of " + ", ".join(KINDS)
            )
        )
        return None
    kind = kinds[0]
    if kind in ("sea", "site"):
        seed = _lonlat(place, block[kind], findings)
        if kind == "sea":
            key, default = "reach_km", DEFAULT_REACH_KM
        else:
            key, default = "radius_km", DEFAULT_RADIUS_KM
        size = _km_value(place, block, key, default, findings)
        if seed is None or size is None:
            return None
        return _Spec(kind, ("sea",) if kind == "sea" else (), seed, size)
    seed = _lonlat(place, block["seed"], findings) if "seed" in block else None
    if "seed" in block and seed is None:
        return None
    if kind == "country":
        code = str(block["country"])
        if code not in data.countries:
            findings.append(
                RegionFinding(
                    place,
                    "unknown-country",
                    f"no country '{code}' in the map data; {_country_hint(code, data)}",
                )
            )
            return None
        return _Spec(kind, ("country", code), seed)
    listed = block["provinces"]
    if not isinstance(listed, list) or not listed:
        findings.append(
            RegionFinding(place, "bad-region", "provinces must be a list of ISO 3166-2 codes")
        )
        return None
    codes = tuple(sorted({str(c) for c in listed}))
    unknown = [c for c in codes if c not in data.geoms]
    for code in unknown:
        findings.append(
            RegionFinding(
                place,
                "unknown-province",
                f"no province '{code}' in the map data; {_province_hint(code, data)}",
            )
        )
    return None if unknown else _Spec(kind, ("provinces", *codes), seed)


def _describe(base: tuple[str, ...]) -> str:
    if base[0] == "provinces":
        return "provinces " + ", ".join(base[1:])
    if base[0] == "country":
        return f"country {base[1]}"
    return "the sea inside the theatre"


# --- building ----------------------------------------------------------------


def _bases(specs: dict[str, _Spec], data: mapdata_mod.MapData) -> dict[tuple, BaseGeometry]:
    """Each land base once, however many places share it."""
    out: dict[tuple, BaseGeometry] = {}
    for spec in specs.values():
        if spec.base in out or spec.kind not in ("provinces", "country"):
            continue
        if spec.kind == "provinces":
            out[spec.base] = mapdata_mod.provinces(spec.base[1:], data)
        else:
            out[spec.base] = data.country(spec.base[1])
    return out


def _theatre(specs, bases, display, findings) -> tuple[float, float, float, float]:
    given = display.get("theatre")
    if given is not None:
        numbers = (
            isinstance(given, list | tuple)
            and len(given) == 4
            and all(isinstance(v, int | float) and not isinstance(v, bool) for v in given)
        )
        if numbers and given[0] < given[2] and given[1] < given[3]:
            return tuple(float(v) for v in given)
        findings.append(
            RegionFinding(
                "display.theatre",
                "bad-theatre",
                f"{given!r} is not [lon0, lat0, lon1, lat1] with lon0 < lon1 and lat0 < lat1",
            )
        )
    parts = list(bases.values())
    parts += [_disc(s.seed, s.size_km) for s in specs.values() if s.kind in ("sea", "site")]
    if not parts:
        return (-180.0, -90.0, 180.0, 90.0)
    x0, y0, x1, y1 = (float(v) for v in shapely.total_bounds(parts))
    m = MARGIN_DEGREES
    return (
        max(-180.0, round(x0 - m, 1)),
        max(-90.0, round(y0 - m, 1)),
        min(180.0, round(x1 + m, 1)),
        min(90.0, round(y1 + m, 1)),
    )


def _split(members, specs, area, frame, findings) -> dict[str, BaseGeometry]:
    """One base among the places on it: all of it for one place, Voronoi cells
    among their seeds for several."""
    if len(members) == 1:
        return {members[0]: area}
    seedless = [p for p in members if specs[p].seed is None]
    for p in seedless:
        others = ", ".join(q for q in members if q != p)
        message = f"shares its base with {others}, so it needs a seed to split it"
        findings.append(RegionFinding(p, "missing-seed", message))
    if seedless:
        return {}
    for i, p in enumerate(members):
        for q in members[:i]:
            if _km_between(specs[p].seed, specs[q].seed) < MIN_SEED_KM:
                findings.append(
                    RegionFinding(
                        p,
                        "seeds-too-close",
                        f"its seed is within {MIN_SEED_KM:g} km of {q}'s, so the two "
                        "cannot split their base",
                    )
                )
                return {}
    seeds = MultiPoint([specs[p].seed for p in members])
    cells = shapely.voronoi_polygons(seeds, extend_to=frame, ordered=True)
    return {
        p: cell.intersection(area)
        for p, cell in zip(members, shapely.get_parts(cells), strict=True)
    }


def _carve(place, spec, shapes, sea, frame, findings) -> None:
    """A site takes its disc out of every region it overlaps."""
    centre = Point(spec.seed)
    if not (sea.intersects(centre) or any(g.intersects(centre) for g in shapes.values())):
        message = "its centre is in no region and in no water in the theatre"
        findings.append(RegionFinding(place, "site-outside", message))
        return
    disc = _disc(spec.seed, spec.size_km).intersection(frame)
    for other in list(shapes):
        shapes[other] = shapes[other].difference(disc)
    shapes[place] = disc


def _kept(shapes, specs, findings) -> dict[str, BaseGeometry]:
    """Only regions a room could see. An empty one, or one smaller than a default
    site, is a finding and gets no polygon."""
    smallest = math.pi * DEFAULT_RADIUS_KM**2
    kept: dict[str, BaseGeometry] = {}
    for place, geom in sorted(shapes.items()):
        geom = _polygonal(geom)
        if geom.is_empty:
            findings.append(RegionFinding(place, "empty-region", "its region came out empty"))
            continue
        km2 = _local(geom, geom.centroid.y).area
        if specs[place].kind != "site" and km2 < smallest:
            findings.append(
                RegionFinding(
                    place,
                    "region-too-small",
                    f"its region is {km2:.0f} km², smaller than a site of "
                    f"{DEFAULT_RADIUS_KM:g} km; are two seeds too close?",
                )
            )
            continue
        kept[place] = geom
    return kept


def _label(spec: _Spec, geom: BaseGeometry) -> tuple[float, float]:
    """The seed when the region still holds it, else the pole of inaccessibility
    of its largest part: a point inside, away from the border."""
    if spec.seed is not None and geom.intersects(Point(spec.seed)):
        return spec.seed
    largest = max(shapely.get_parts(geom), key=lambda part: part.area)
    point = polylabel(largest, tolerance=0.01)
    return float(point.x), float(point.y)


def _coords(geom: BaseGeometry) -> list:
    """GeoJSON MultiPolygon coordinates on the 0.001° grid."""
    snapped = shapely.set_precision(geom, GRID)
    polygons = [p for p in shapely.get_parts(snapped) if p.geom_type == "Polygon"]
    return [
        [
            [[round(x, DECIMALS), round(y, DECIMALS)] for x, y in ring.coords]
            for ring in (p.exterior, *p.interiors)
        ]
        for p in polygons
    ]


def compute(places: dict[str, dict], display: dict, *, mapdata=None) -> Regions:
    """Every place with a `region` block as a polygon and a label point, the
    theatre, the land outline inside it, the computed adjacency, and the findings.
    `mapdata` defaults to the packaged data; tests pass a synthetic one."""
    data = mapdata if mapdata is not None else mapdata_mod.load_admin1()
    findings: list[RegionFinding] = []
    specs: dict[str, _Spec] = {}
    for place in sorted(places):
        if "region" in (places[place] or {}):
            spec = _parse(place, places[place]["region"], data, findings)
            if spec is not None:
                specs[place] = spec
    bases = _bases(specs, data)
    theatre = _theatre(specs, bases, display or {}, findings)
    frame = box(*theatre)
    land = data.land(theatre)
    sea = frame.difference(land)
    bases[("sea",)] = sea

    groups: dict[tuple, list[str]] = {}
    for place, spec in specs.items():
        if spec.kind != "site":
            groups.setdefault(spec.base, []).append(place)
    shapes: dict[str, BaseGeometry] = {}
    for base, members in groups.items():
        area = bases[base].intersection(frame)
        seeded = [p for p in members if specs[p].seed is not None]
        off = [p for p in seeded if not area.intersects(Point(specs[p].seed))]
        for p in off:
            lon, lat = specs[p].seed
            message = f"its seed [{lat}, {lon}] is not on {_describe(base)}"
            findings.append(RegionFinding(p, "seed-outside-base", message))
        if off:
            continue
        try:
            shapes.update(_split(members, specs, area, frame, findings))
        except GEOSException as exc:
            findings += [RegionFinding(p, "geometry-error", str(exc)) for p in members]
    for place in list(shapes):
        if specs[place].kind == "sea":
            reach = _disc(specs[place].seed, specs[place].size_km)
            shapes[place] = shapes[place].intersection(reach)
    for place, spec in specs.items():
        if spec.kind == "site":
            _carve(place, spec, shapes, sea, frame, findings)
    kept = _kept(shapes, specs, findings)

    return Regions(
        places={
            place: {
                "polygon": _coords(geom),
                "label": [round(v, DECIMALS) for v in _label(specs[place], geom)],
                "kind": specs[place].kind,
            }
            for place, geom in sorted(kept.items())
        },
        adjacency={place: [] for place in sorted(kept)},
        theatre=theatre,
        land=_coords(land),
        findings=findings,
        mapdata=data.version,
    )
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_regions.py -q`
Expected: PASS (15 tests).

- [ ] **Step 6: Commit**

```bash
git add src/casus/geo/digest.py src/casus/geo/regions.py tests/test_regions.py
git commit -m "feat(geo): regions from provinces, countries, sea zones and sites"
```

---

### Task 4: Region findings, and Review Focus 4

**Files:**
- Modify: `src/casus/geo/regions.py`
- Test: `tests/test_regions.py`

**Interfaces:**
- Produces: the finding codes `bad-region`, `bad-theatre`, `unknown-province`,
  `unknown-country`, `seed-outside-base`, `missing-seed`, `seeds-too-close`, `empty-region`,
  `region-too-small`, `site-outside`, `geometry-error` (all in Task 3's code) and
  `latlon-disagrees` (added here, `_latlon(place, spec, geom, findings)`).

Every finding but `latlon-disagrees` is already in Task 3's code, because parsing and splitting
cannot be written without them. This task pins each with a test; only the lat/lon test fails
first. Step 5 breaks the seed check on purpose to show the Review Focus test can fail.

- [ ] **Step 1: Write the tests**

Add `import itertools` to the imports of `tests/test_regions.py` and append:

```python
def _codes(result: regions.Regions) -> list[str]:
    return [f.code for f in result.findings]


def test_an_unknown_province_names_the_provinces_of_its_country():
    result = _compute({"x": {"region": {"provinces": ["AA-9"]}}})
    [finding] = result.findings
    assert (finding.place, finding.code) == ("x", "unknown-province")
    assert "AA-4 (Square AA-4)" in finding.message
    assert "x" not in result.places


def test_an_unknown_country_names_the_closest_codes():
    [finding] = _compute({"x": {"region": {"country": "AB"}}}).findings
    assert finding.code == "unknown-country"
    assert "AA (Alpha)" in finding.message


def test_a_seed_outside_its_own_base_is_a_finding():
    result = _compute({"x": {"region": {"provinces": ["AA-1"], "seed": [3.0, 3.0]}}})
    assert _codes(result) == ["seed-outside-base"]
    assert result.places == {}


def test_two_places_on_one_base_need_a_seed_each():
    result = _compute(
        {
            "x": {"region": {"provinces": ["AA-2"], "seed": [1.0, 3.0]}},
            "y": {"region": {"provinces": ["AA-2"]}},
        }
    )
    assert [(f.place, f.code) for f in result.findings] == [("y", "missing-seed")]
    assert result.places == {}


@pytest.mark.parametrize("offset", [0.0, 1e-9, 0.005])
def test_near_coincident_seeds_are_a_finding(offset):
    """GEOS raises on coincident seeds and returns cells that do not split the base
    for nearly coincident ones. Either way the answer is a finding: never an
    exception, never an empty polygon. 0.005° is about 0.56 km here."""
    result = _compute(
        {
            "x": {"region": {"provinces": ["AA-1"], "seed": [1.0, 1.0]}},
            "y": {"region": {"provinces": ["AA-1"], "seed": [1.0, 1.0 + offset]}},
            "z": {"region": {"provinces": ["AA-4"]}},
        }
    )
    assert _codes(result) == ["seeds-too-close"]
    assert set(result.places) == {"z"}
    assert all(p["polygon"] for p in result.places.values())


def test_seed_on_a_border_belongs_to_one_region():
    """A seed exactly on the border between two bases is on its own base (the
    boundary counts), the regions around it never overlap, and a site on that
    border is the one region that holds the point."""
    result = _compute(
        {
            "west-a": {"region": {"provinces": ["AA-1"], "seed": [1.0, 2.0]}},
            "west-b": {"region": {"provinces": ["AA-1"], "seed": [1.0, 0.5]}},
            "east": {"region": {"provinces": ["AA-2"]}},
            "post": {"region": {"site": [1.0, 2.0], "radius_km": 10}},
        }
    )
    assert result.findings == []
    shapes = {p: _shape(result, p) for p in result.places}
    assert set(shapes) == {"west-a", "west-b", "east", "post"}
    assert all(not s.is_empty for s in shapes.values())
    for p, q in itertools.combinations(shapes, 2):
        assert shapes[p].intersection(shapes[q]).area == pytest.approx(0.0, abs=1e-9), (p, q)
    assert [p for p, s in shapes.items() if s.contains(Point(2.0, 1.0))] == ["post"]
    assert shapes["west-a"].contains(Point(result.places["west-a"]["label"]))


def test_a_region_carved_away_entirely_is_a_finding():
    result = _compute(
        {
            "land": {"region": {"provinces": ["AA-1"]}},
            "base": {"region": {"site": [1.0, 1.0], "radius_km": 300}},
        }
    )
    assert [(f.place, f.code) for f in result.findings] == [("land", "empty-region")]
    assert set(result.places) == {"base"}


def test_a_region_smaller_than_a_site_is_a_finding():
    result = _compute({"x": {"region": {"sea": [1.0, -1.0], "reach_km": 5}}})
    assert _codes(result) == ["region-too-small"]


def test_a_site_in_no_region_and_no_water_is_a_finding():
    """BB-1 is land, and no place claims it."""
    result = _compute({"base": {"region": {"site": [1.0, 5.0]}}})
    assert _codes(result) == ["site-outside"]


def test_latlon_that_disagrees_with_the_region_is_a_finding():
    result = _compute(
        {"x": {"region": {"provinces": ["AA-1"]}, "attrs": {"lat": 1.0, "lon": 7.0}}}
    )
    assert _codes(result) == ["latlon-disagrees"]


def test_latlon_inside_the_region_is_not_a_finding():
    result = _compute(
        {"x": {"region": {"provinces": ["AA-1"]}, "attrs": {"lat": 1.0, "lon": 1.0}}}
    )
    assert result.findings == []


@pytest.mark.parametrize(
    "block",
    [
        {},
        {"provinces": ["AA-1"], "country": "AA"},
        {"provinces": "AA-1"},
        {"site": [1.0]},
        {"sea": [1.0, -1.0], "reach_km": -5},
        "AA-1",
    ],
)
def test_a_malformed_region_block_is_a_finding(block):
    assert _codes(_compute({"x": {"region": block}})) == ["bad-region"]


def test_a_malformed_theatre_is_a_finding():
    result = _compute({"x": {"region": {"provinces": ["AA-1"]}}}, {"theatre": [5, 0, 1, 1]})
    assert _codes(result) == ["bad-theatre"]
```

- [ ] **Step 2: Run to verify the one expected failure**

Run: `uv run pytest tests/test_regions.py -q`
Expected: one FAIL, `test_latlon_that_disagrees_with_the_region_is_a_finding`, with
`assert [] == ['latlon-disagrees']`. Every other test passes.

- [ ] **Step 3: Implement `_latlon`**

In `src/casus/geo/regions.py`, add after `_kept`:

```python
def _latlon(place: str, spec: dict, geom: BaseGeometry, findings: list) -> None:
    """A place that also carries lat/lon attributes must put them on or near its
    region: no farther away than the region's own size."""
    attrs = spec.get("attrs") or {}
    lat, lon = attrs.get("lat"), attrs.get("lon")
    if not isinstance(lat, int | float) or not isinstance(lon, int | float):
        return
    local = _local(geom, lat)
    size = math.sqrt(local.area / math.pi)
    off = local.distance(_local(Point(lon, lat), lat))
    if off > size:
        findings.append(
            RegionFinding(
                place,
                "latlon-disagrees",
                f"lat/lon [{lat}, {lon}] is {off:.0f} km from its region, more than the "
                f"region's own size of {size:.0f} km (the radius of a circle of its area)",
            )
        )
```

and in `compute`, right after `kept = _kept(shapes, specs, findings)`:

```python
    for place, geom in kept.items():
        _latlon(place, places[place] or {}, geom, findings)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_regions.py -q`
Expected: PASS.

- [ ] **Step 5: Break it on purpose**

In `_split`, delete the `for i, p in enumerate(members):` loop that checks `MIN_SEED_KM`. Run
`uv run pytest tests/test_regions.py -q -k near_coincident`. Expected: FAIL in all three cases: `0.0` with
`assert ['geometry-error', 'geometry-error'] == ['seeds-too-close']` (GEOS raised), `1e-09` and
`0.005` with `assert [] == ['seeds-too-close']` (a split that means nothing, and no finding).
Restore the loop and rerun: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/casus/geo/regions.py tests/test_regions.py
git commit -m "feat(geo): every region finding the spec lists, with a test each"
```

---

### Task 5: Computed adjacency

**Files:**
- Modify: `src/casus/geo/regions.py`
- Test: `tests/test_regions.py`

**Interfaces:**
- Produces: `Regions.adjacency: dict[str, list[str]]`, sorted, symmetric: two regions are
  neighbours when they share more than `MIN_BORDER_KM` of border. That one test also covers a land
  region meeting a sea zone at the coast and a site meeting every region its disc was carved
  from.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_regions.py`:

```python
def test_squares_sharing_an_edge_are_neighbours():
    result = _compute(
        {"a": {"region": {"provinces": ["AA-2"]}}, "b": {"region": {"provinces": ["BB-1"]}}}
    )
    assert result.adjacency == {"a": ["b"], "b": ["a"]}


def test_squares_touching_at_a_corner_are_not():
    result = _compute(
        {"a": {"region": {"provinces": ["AA-4"]}}, "b": {"region": {"provinces": ["BB-1"]}}}
    )
    assert result.adjacency == {"a": [], "b": []}


def test_a_land_region_and_a_sea_zone_meeting_at_the_coast_are_neighbours():
    result = _compute(
        {
            "land": {"region": {"provinces": ["AA-1"]}},
            "gulf": {"region": {"sea": [1.0, -0.5], "reach_km": 100}},
        }
    )
    assert result.adjacency["land"] == ["gulf"]


def test_a_sea_zone_that_does_not_reach_the_coast_is_not_a_neighbour():
    result = _compute(
        {
            "land": {"region": {"provinces": ["AA-1"]}},
            "gulf": {"region": {"sea": [1.0, -1.5], "reach_km": 50}},
        }
    )
    assert result.adjacency["land"] == []


def test_a_site_borders_the_regions_its_disc_was_carved_from():
    result = _compute(
        {
            "west": {"region": {"provinces": ["AA-1"]}},
            "east": {"region": {"provinces": ["AA-2"]}},
            "far": {"region": {"provinces": ["AA-4"]}},
            "post": {"region": {"site": [1.0, 2.0], "radius_km": 10}},
        }
    )
    assert result.adjacency["post"] == ["east", "west"]
    assert result.adjacency["west"] == ["east", "post"]


def test_on_the_packaged_data_havana_borders_matanzas_and_the_straits():
    """The one test here on real borders: the classroom case, measured."""
    places = {
        "habana": {"region": {"provinces": ["CU-03", "CU-16"]}},
        "matanzas": {"region": {"provinces": ["CU-04"]}},
        "straits": {"region": {"sea": [24.2, -81.3], "reach_km": 240}},
    }
    result = compute(places, {"theatre": [-84.0, 21.5, -80.0, 25.5]})
    assert result.findings == []
    assert result.adjacency["habana"] == ["matanzas", "straits"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_regions.py -q -k "neighbour or borders"`
Expected: FAIL, e.g. `assert {'a': [], 'b': []} == {'a': ['b'], 'b': ['a']}`. The corner and
the "does not reach" tests pass already, since the lists are empty.

- [ ] **Step 3: Implement**

In `src/casus/geo/regions.py`, add before `compute`:

```python
def _adjacency(shapes: dict[str, BaseGeometry]) -> dict[str, list[str]]:
    """Neighbours share more than MIN_BORDER_KM of border. A land region meets a
    sea zone along the coast by the same test, and a site meets every region its
    disc was carved from. Squares touching at a corner share no length. Borders
    are compared within the 0.001° grid, because two regions cut by separate
    operations can differ by float noise along the edge they share."""
    ids = sorted(shapes)
    out: dict[str, list[str]] = {place: [] for place in ids}
    for i, p in enumerate(ids):
        for q in ids[i + 1 :]:
            if shapes[p].distance(shapes[q]) > GRID:
                continue
            shared = shapes[p].boundary.intersection(shapes[q].buffer(GRID))
            if shared.is_empty:
                continue
            if _local(shared, shared.centroid.y).length > MIN_BORDER_KM:
                out[p].append(q)
                out[q].append(p)
    return out
```

In `compute`, replace `adjacency={place: [] for place in sorted(kept)},` with:

```python
        adjacency=_adjacency(kept),
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_regions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/casus/geo/regions.py tests/test_regions.py
git commit -m "feat(geo): adjacency from shared borders and coasts"
```

---

### Task 6: `casus regions`

**Files:**
- Modify: `src/casus/cli.py`, `tests/helpers.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `regions.compute(places, display)`, `regions.region_digest(places, theatre)`,
  `Regions.to_json(digest)`.
- Produces: `casus regions <scenario>`: exit 0 and `regions.json` written when there are no
  findings; exit 1, the findings printed and nothing written otherwise; exit 2 when the scenario
  has no region blocks or cannot be read. `cli.py` imports `casus.geo` only inside `_regions`.
- Produces test helpers in `tests/helpers.py`: `CUBA_BLOCKS`, `SMOKE_REGION_BLOCKS`,
  `SMOKE_REGION_GRAPH`, `smoke_with_regions(tmp_path, blocks, *, keep_lists=(), change=None)
  -> pathlib.Path`, `write_regions(directory, adjacency, **overrides) -> pathlib.Path`.

- [ ] **Step 1: Add the helpers**

In `tests/helpers.py`, add to the imports:

```python
import json
import pathlib

import yaml
from v1shape import ActorState, Force, RegionState, WorldState

from casus.geo.digest import region_digest
```

(the `from v1shape import ...` line is already there; keep one) and append:

```python
SMOKE_DIR = pathlib.Path(__file__).parent.parent / "scenarios" / "smoke"

#: The smoke scenario's three places on real Cuban provinces and the Straits of
#: Florida, for the tests that run `casus regions` on the packaged map data.
CUBA_BLOCKS = {
    "b-home": {"provinces": ["CU-03", "CU-16"]},
    "border": {"provinces": ["CU-04"]},
    "r-home": {"sea": [24.2, -81.3], "reach_km": 240},
}

#: Region blocks nobody computes: the loading tests write regions.json by hand
#: with SMOKE_REGION_GRAPH, so they need neither shapely nor the map data.
SMOKE_REGION_BLOCKS = {
    "b-home": {"provinces": ["XX-1"]},
    "border": {"provinces": ["XX-2"]},
    "r-home": {"provinces": ["XX-3"]},
}
SMOKE_REGION_GRAPH = {
    "b-home": ["border"],
    "border": ["b-home", "r-home"],
    "r-home": ["border"],
}


def smoke_with_regions(tmp_path, blocks, *, keep_lists=(), change=None) -> pathlib.Path:
    """A copy of the smoke scenario whose places carry `blocks` as region blocks.
    A place not named in `keep_lists` loses its plain adjacency list, so the
    computed graph fills it; each place loses its lat/lon, since the blocks put it
    elsewhere. `change` edits the data before it is written."""
    data = yaml.safe_load((SMOKE_DIR / "scenario.yaml").read_text())
    for place_id, block in blocks.items():
        place = data["places"][place_id]
        place["region"] = block
        place["attrs"].pop("lat", None)
        place["attrs"].pop("lon", None)
        if place_id not in keep_lists:
            del place["adjacency"]
    if change is not None:
        change(data)
    directory = tmp_path / "smoke-regions"
    directory.mkdir()
    (directory / "scenario.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    (directory / "rules.py").write_text((SMOKE_DIR / "rules.py").read_text())
    return directory


def write_regions(directory, adjacency, **overrides) -> pathlib.Path:
    """A regions.json written by hand, fresh for the scenario beside it."""
    data = yaml.safe_load((directory / "scenario.yaml").read_text())
    theatre = (data.get("display") or {}).get("theatre")
    doc = {
        "version": 1,
        "mapdata": "hand-written",
        "digest": region_digest(data["places"], theatre),
        "theatre": [-84.0, 21.5, -80.0, 25.5],
        "land": [],
        "places": {},
        "adjacency": adjacency,
        **overrides,
    }
    path = directory / "regions.json"
    path.write_text(json.dumps(doc))
    return path
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_cli.py`, adding `import json`, `import yaml`,
`from casus.geo.regions import region_digest` and
`from helpers import CUBA_BLOCKS, smoke_with_regions` to its imports:

```python
def test_regions_writes_regions_json_from_the_packaged_map(tmp_path, capsys):
    directory = smoke_with_regions(tmp_path, CUBA_BLOCKS)
    assert cli.main(["regions", str(directory)]) == 0
    doc = json.loads((directory / "regions.json").read_text())
    places = yaml.safe_load((directory / "scenario.yaml").read_text())["places"]
    assert doc["digest"] == region_digest(places)
    assert doc["adjacency"]["b-home"] == ["border", "r-home"]
    assert set(doc["places"]) == set(CUBA_BLOCKS)
    assert "wrote" in capsys.readouterr().out


def test_regions_with_findings_writes_nothing_and_fails(tmp_path, capsys):
    blocks = {**CUBA_BLOCKS, "border": {"provinces": ["CU-02"]}}
    directory = smoke_with_regions(tmp_path, blocks)
    assert cli.main(["regions", str(directory)]) == 1
    out = capsys.readouterr().out
    assert "unknown-province" in out and "CU-03 (Ciudad de la Habana)" in out
    assert not (directory / "regions.json").exists()


def test_regions_on_a_scenario_without_region_blocks_says_so(capsys):
    assert cli.main(["regions", str(SCENARIOS / "smoke")]) == 2
    assert "no region blocks" in capsys.readouterr().err
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_cli.py -q -k regions`
Expected: FAIL with `SystemExit: 2` from argparse (`invalid choice: 'regions'`).

- [ ] **Step 4: Implement**

In `src/casus/cli.py`, next to the other subparsers in `main`:

```python
    regions_cmd = sub.add_parser(
        "regions", help="compute a scenario's map regions and adjacency into regions.json"
    )
    regions_cmd.add_argument("scenario", help="a scenario directory")
```

and the dispatch branch, with the other `if args.command == ...` branches:

```python
    if args.command == "regions":
        return _regions(args)
```

Then add:

```python
def _regions(args) -> int:
    # Imported here: only this command needs shapely and the map data.
    import json

    import yaml

    from .geo import regions as regions_mod

    directory = pathlib.Path(args.scenario)
    try:
        data = yaml.safe_load((directory / "scenario.yaml").read_text()) or {}
    except OSError as exc:
        print(f"casus: {exc}", file=sys.stderr)
        return 2
    places = data.get("places") or {}
    display = data.get("display") or {}
    if not any("region" in (spec or {}) for spec in places.values()):
        print(f"casus: {directory} has no region blocks; nothing to compute", file=sys.stderr)
        return 2
    result = regions_mod.compute(places, display)
    for finding in result.findings:
        print(f"  {finding}")
    if result.findings:
        count = len(result.findings)
        print(f"casus: {directory}: {count} finding(s); regions.json not written")
        return 1
    out = directory / "regions.json"
    digest = regions_mod.region_digest(places, display.get("theatre"))
    out.write_text(json.dumps(result.to_json(digest), separators=(",", ":")) + "\n")
    for place_id, neighbours in result.adjacency.items():
        print(f"  {place_id}: {', '.join(neighbours) or '(none)'}")
    size = out.stat().st_size / 1024
    print(f"casus: wrote {out} — {len(result.places)} regions, {size:.0f} KiB")
    return 0
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run ruff check --fix src tests && uv run pytest tests/test_cli.py -q`
Expected: ruff clean, then PASS.

- [ ] **Step 6: Commit**

```bash
git add src/casus/cli.py tests/helpers.py tests/test_cli.py
git commit -m "feat(cli): casus regions writes a scenario's regions.json"
```

---

### Task 7: `Scenario.load` reads `regions.json`

**Files:**
- Modify: `src/casus/scenario.py`, `src/casus/cli.py` (`_validate`), `src/casus/server/app.py`
  (`_card`)
- Test: `tests/test_scenario.py`, `tests/test_cli.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `geo.digest.region_digest`, `validate.Finding`.
- Produces: `Scenario.regions: dict | None` (the loaded `regions.json`), `Scenario.warnings:
  tuple[Finding, ...]` (code `adjacency-differs`), `scenario.REGIONS_FILE = "regions.json"`.
  `Scenario.load` raises `ScenarioError` naming `casus regions <dir>` when `regions.json` is
  missing or stale. `Scenario.from_parts` refuses a place whose `adjacency` is a mapping.
  `casus validate` prints warnings as `  warning: ...` and they do not change its exit code.

- [ ] **Step 1: Write the failing tests**

In `tests/test_scenario.py`, add to the imports `import json`, `import re`, `import subprocess`,
`import sys` and
`from helpers import SMOKE_REGION_BLOCKS, SMOKE_REGION_GRAPH, smoke_with_regions, write_regions`,
then append:

```python
# --- regions -------------------------------------------------------------------


def test_region_blocks_without_regions_json_fail_with_the_command(tmp_path):
    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS)
    with pytest.raises(ScenarioError, match=re.escape(f"run: casus regions {directory}")):
        Scenario.load(directory, validate=False)


def test_a_stale_regions_json_fails_with_the_command(tmp_path):
    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS)
    write_regions(directory, SMOKE_REGION_GRAPH)
    manifest = directory / "scenario.yaml"
    manifest.write_text(manifest.read_text().replace("XX-3", "XX-4"))
    with pytest.raises(ScenarioError, match="stale") as excinfo:
        Scenario.load(directory, validate=False)
    assert f"casus regions {directory}" in str(excinfo.value)


def test_the_computed_graph_fills_each_place_adjacency(tmp_path):
    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS)
    write_regions(directory, SMOKE_REGION_GRAPH)
    world = Scenario.load(directory, validate=False).initial_state()
    assert {p: list(place.adjacency) for p, place in world.places.items()} == SMOKE_REGION_GRAPH


def test_exceptions_add_and_remove_an_edge_at_both_ends(tmp_path):
    def exceptions(data):
        data["places"]["b-home"]["adjacency"] = {"add": ["r-home"], "remove": ["border"]}

    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS, change=exceptions)
    write_regions(directory, SMOKE_REGION_GRAPH)
    world = Scenario.load(directory, validate=False).initial_state()
    assert world.places["b-home"].adjacency == ("r-home",)
    assert world.places["r-home"].adjacency == ("b-home", "border")
    assert world.places["border"].adjacency == ("r-home",)


def test_a_plain_list_stays_authoritative_and_a_disagreement_is_a_warning(tmp_path):
    def listed(data):
        data["places"]["r-home"]["adjacency"] = ["border", "b-home"]

    directory = smoke_with_regions(
        tmp_path, SMOKE_REGION_BLOCKS, keep_lists=("r-home",), change=listed
    )
    write_regions(directory, SMOKE_REGION_GRAPH)
    scenario = Scenario.load(directory, validate=False)
    assert scenario.initial_state().places["r-home"].adjacency == ("border", "b-home")
    [warning] = scenario.warnings
    assert warning.code == "adjacency-differs" and "'r-home'" in warning.message


def test_a_plain_list_that_matches_the_geometry_is_silent(tmp_path):
    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS, keep_lists=("border",))
    write_regions(directory, SMOKE_REGION_GRAPH)
    assert Scenario.load(directory, validate=False).warnings == ()


def test_an_exception_naming_an_unknown_place_fails(tmp_path):
    def exceptions(data):
        data["places"]["border"]["adjacency"] = {"add": ["nowhere"]}

    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS, change=exceptions)
    write_regions(directory, SMOKE_REGION_GRAPH)
    with pytest.raises(ScenarioError, match="unknown place 'nowhere'"):
        Scenario.load(directory, validate=False)


def test_from_parts_refuses_exceptions_it_cannot_resolve():
    data = yaml.safe_load((SMOKE / "scenario.yaml").read_text())
    data["places"]["border"]["adjacency"] = {"remove": ["b-home"]}
    with pytest.raises(ScenarioError, match="only Scenario.load applies them"):
        Scenario.from_parts(data, (SMOKE / "rules.py").read_text())


def test_a_scenario_with_regions_validates_and_carries_them(tmp_path):
    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS)
    written = json.loads(write_regions(directory, SMOKE_REGION_GRAPH).read_text())
    scenario = Scenario.load(directory)
    assert scenario.regions == written


def test_loading_and_running_with_regions_never_import_shapely(tmp_path):
    """Running, replaying and bundling read regions.json. Only `casus regions`
    needs shapely and the map data."""
    directory = smoke_with_regions(tmp_path, SMOKE_REGION_BLOCKS)
    write_regions(directory, SMOKE_REGION_GRAPH)
    script = textwrap.dedent(
        f"""
        import pathlib, sys
        from casus import bundle, engine
        from casus.scenario import Scenario
        from helpers import FakeEngine
        scenario = Scenario.load({str(directory)!r}, validate=False)
        out = pathlib.Path({str(tmp_path / "run.jsonl")!r})
        engines = {{a: FakeEngine() for a in scenario.actors}}
        engine.run(scenario, seed=1, out=out, engines=engines, turns=1)
        engine.replay(out)
        bundle.bundle(out, out.with_suffix(".html"))
        assert "shapely" not in sys.modules, "shapely was imported"
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        cwd=pathlib.Path(__file__).parent,
    )
    assert done.returncode == 0, done.stderr[-800:]
```

Add `import pathlib` too if the file does not already import it.

Append to `tests/test_cli.py` (add `SMOKE_REGION_BLOCKS`, `SMOKE_REGION_GRAPH`, `write_regions`
to its `helpers` import):

```python
def test_validate_prints_an_adjacency_warning_without_failing(tmp_path, capsys):
    def listed(data):
        data["places"]["r-home"]["adjacency"] = ["border", "b-home"]

    directory = smoke_with_regions(
        tmp_path, SMOKE_REGION_BLOCKS, keep_lists=("r-home",), change=listed
    )
    write_regions(directory, SMOKE_REGION_GRAPH)
    assert cli.main(["validate", str(directory), "--turns", "2"]) == 0
    out = capsys.readouterr().out
    assert "warning: " in out and "adjacency-differs" in out
```

Append to `tests/test_server.py` (add `from helpers import SMOKE_REGION_BLOCKS,
smoke_with_regions` to its imports):

```python
def test_a_scenario_with_a_stale_map_is_listed_invalid_with_the_command(tmp_path, runs):
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    directory = smoke_with_regions(scenarios, SMOKE_REGION_BLOCKS)
    client = TestClient(create_app(scenarios_dir=scenarios, runs_dir=runs))
    [card] = client.get("/api/scenarios").json()
    assert card["valid"] is False
    assert f"casus regions {directory}" in card["findings"][0]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scenario.py tests/test_cli.py tests/test_server.py -q -k "region or stale or warning"`
Expected: FAIL. The loading tests fail with `ScenarioError: place 'b-home' is adjacent to unknown
place 'add'` or with `AttributeError: 'Scenario' object has no attribute 'regions'`; the missing
`regions.json` test fails with `DID NOT RAISE`.

- [ ] **Step 3: Implement in `src/casus/scenario.py`**

Add to the imports:

```python
import json
```

```python
from .geo.digest import region_digest
from .validate import Finding
```

(keep `from .validate.static import check_source`), and below `SHIPPED`:

```python
#: Where `casus regions` writes a scenario's polygons and computed adjacency.
REGIONS_FILE = "regions.json"
```

Add two fields at the end of `Scenario`, after `module`:

```python
    #: regions.json as loaded, when the scenario has region blocks. The transcript
    #: carries it, so replay and the viewer need nothing else.
    regions: dict[str, Any] | None = dataclasses.field(default=None, compare=False, repr=False)
    #: Findings that do not stop a load: a plain adjacency list the regions disagree with.
    warnings: tuple[Finding, ...] = dataclasses.field(default=(), compare=False, repr=False)
```

In `load`, replace the lines from `rules_path = ...` to `scenario = cls.from_parts(...)` with:

```python
        regions, warnings = _apply_regions(directory, data)
        rules_path = cls._rules_path(directory, data.get("rules"))
        scenario = cls.from_parts(data, rules_path.read_text(), origin=str(rules_path))
        scenario = dataclasses.replace(scenario, regions=regions, warnings=tuple(warnings))
```

Add after `load_rules`:

```python
def _apply_regions(directory: pathlib.Path, data: dict[str, Any]) -> tuple[dict | None, list]:
    """Fill each place's adjacency from regions.json: the computed graph, then the
    YAML's `add`/`remove` exceptions, applied at both ends so no edge is one-way.
    A plain list stays authoritative for its place; where it disagrees with the
    regions that is a warning, so an older scenario migrates one place at a time.
    Needs neither shapely nor the map data: `casus regions` did the geometry."""
    places = data.get("places")
    if not isinstance(places, dict) or not any(
        isinstance(spec, dict) and "region" in spec for spec in places.values()
    ):
        return None, []
    path = directory / REGIONS_FILE
    fix = f"run: casus regions {directory}"
    if not path.is_file():
        raise ScenarioError(f"{directory} has region blocks but no {REGIONS_FILE}; {fix}")
    regions = json.loads(path.read_text())
    theatre = (data.get("display") or {}).get("theatre")
    if regions.get("digest") != region_digest(places, theatre):
        raise ScenarioError(
            f"{path} is stale: the region blocks changed since it was computed; {fix}"
        )
    computed = regions.get("adjacency") or {}
    graph = {
        place_id: set(computed.get(place_id, ()))
        for place_id, spec in places.items()
        if isinstance(spec, dict) and "region" in spec
    }
    for place_id, spec in places.items():
        exceptions = (spec or {}).get("adjacency")
        if not isinstance(exceptions, dict):
            continue
        if place_id not in graph:
            raise ScenarioError(
                f"place '{place_id}' lists adjacency exceptions but has no region block"
            )
        verbs = set(exceptions) - {"add", "remove"}
        if verbs:
            raise ScenarioError(
                f"place '{place_id}': adjacency exceptions are add and remove, "
                f"not {sorted(verbs)}"
            )
        for verb in ("add", "remove"):
            for other in exceptions.get(verb) or ():
                if other not in places:
                    raise ScenarioError(
                        f"place '{place_id}' {verb}s adjacency to unknown place '{other}'"
                    )
                if verb == "add":
                    graph[place_id].add(other)
                    graph.setdefault(other, set()).add(place_id)
                else:
                    graph[place_id].discard(other)
                    graph.get(other, set()).discard(place_id)
    warnings = []
    for place_id, spec in places.items():
        listed = (spec or {}).get("adjacency")
        if isinstance(listed, list):
            if place_id in graph and set(listed) != graph[place_id]:
                warnings.append(
                    Finding(
                        "adjacency-differs",
                        f"place '{place_id}' lists {sorted(listed)}; its region gives "
                        f"{sorted(graph[place_id])}",
                        str(path),
                    )
                )
        elif place_id in graph:
            spec["adjacency"] = sorted(graph[place_id])
    return regions, warnings
```

In `_check_structure`, replace the line `for neighbour in spec.get("adjacency") or ():` with:

```python
        adjacency = spec.get("adjacency") or ()
        if isinstance(adjacency, dict):
            raise ScenarioError(
                f"place '{place_id}' lists adjacency exceptions "
                f"({', '.join(sorted(adjacency))}); only Scenario.load applies them, "
                "from regions.json"
            )
        for neighbour in adjacency:
```

(the body of the loop stays as it is).

- [ ] **Step 4: Print warnings in `casus validate`**

In `src/casus/cli.py`, replace `_validate` with:

```python
def _validate(args) -> int:
    from .scenario import ScenarioInvalid
    from .validate.invariants import check_invariants

    warnings: tuple = ()
    try:
        scenario = Scenario.load(args.scenario)
        warnings = scenario.warnings
        findings = check_invariants(scenario, turns=args.turns)
    except ScenarioInvalid as exc:
        findings = exc.findings
    except (ScenarioError, OSError) as exc:
        print(f"casus: {exc}", file=sys.stderr)
        return 2
    for warning in warnings:
        print(f"  warning: {warning}")
    for finding in findings:
        print(f"  {finding}")
    count = f"{len(findings)} finding(s)" if findings else "no findings"
    print(f"casus: {args.scenario}: {count}")
    return 1 if findings else 0
```

- [ ] **Step 5: Keep the home page up for a scenario with a stale map**

`_card` in `src/casus/server/app.py` reads the counts with `Scenario.load(directory,
validate=False)`, which now raises for a stale or missing `regions.json`, and the whole
`/api/scenarios` answer would fail. The counts need only the YAML. Add `import yaml` to the
imports and replace `data = Scenario.load(directory, validate=False).data` with:

```python
    data = yaml.safe_load((directory / "scenario.yaml").read_text())
```

`_verdict` already turns the `ScenarioError` into `valid: False` and its message into the
findings.

- [ ] **Step 6: Run to verify it passes**

Run: `uv run ruff check --fix src tests` first. The project's isort settings place `helpers`
with `casus` as first-party, and `--fix` puts the new imports where they belong.

Run: `uv run pytest tests/test_scenario.py tests/test_cli.py tests/test_server.py -q`
Expected: PASS.

Then the suites that load every scenario, since `_check_structure` and `load` changed:

Run: `uv run pytest tests/reference tests/test_worldmap.py tests/test_validate_dynamic.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/casus/scenario.py src/casus/cli.py src/casus/server/app.py \
  tests/test_scenario.py tests/test_cli.py tests/test_server.py
git commit -m "feat(scenario): load regions.json, apply adjacency exceptions, refuse a stale map"
```

---

### Task 8: The transcript carries the regions

**Files:**
- Modify: `src/casus/engine.py` (the `scenario` record in `run_async`)
- Test: `tests/test_engine.py`, `tests/test_bundle.py`

**Interfaces:**
- Consumes: `Scenario.regions`.
- Produces: the `scenario` record gains a top-level `regions` key holding `regions.json` as the
  run used it, only when `scenario.regions is not None` (master plan contract).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py`:

```python
def test_the_scenario_record_carries_the_regions_the_run_used(tmp_path):
    regions = {
        "version": 1,
        "theatre": [0.0, 0.0, 1.0, 1.0],
        "land": [],
        "places": {},
        "adjacency": {},
    }
    scenario = dataclasses.replace(_smoke(), regions=regions)
    out = tmp_path / "run.jsonl"
    engine.run(scenario, seed=1, out=out, engines=_engines(scenario), turns=1)
    header = next(r for r in _records(out) if r["kind"] == "scenario")
    assert header["regions"] == regions
    engine.replay(out)


def test_a_run_without_regions_writes_no_regions_key(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(out, turns=1)
    header = next(r for r in _records(out) if r["kind"] == "scenario")
    assert "regions" not in header
```

Append to `tests/test_bundle.py`:

```python
def test_the_bundle_carries_the_regions_the_run_used(transcript, tmp_path):
    records = engine.read_records(transcript)
    records[0]["regions"] = {
        "version": 1,
        "theatre": [0.0, 0.0, 1.0, 1.0],
        "land": [],
        "places": {},
        "adjacency": {},
    }
    source = tmp_path / "with-regions.jsonl"
    source.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    html = bundle.bundle(source, tmp_path / "demo.html").read_text()
    assert '"theatre":[0.0,0.0,1.0,1.0]' in html
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_engine.py tests/test_bundle.py -q -k regions`
Expected: `test_the_scenario_record_carries_the_regions_the_run_used` FAILS with
`KeyError: 'regions'`. The bundle test passes already: it pins that `viewer_records` keeps the
key.

- [ ] **Step 3: Implement**

In `src/casus/engine.py`, replace the `transcript.write({... "kind": "scenario" ...})` call in
`run_async` with:

```python
    header = {
        "kind": "scenario",
        "turn": 0,
        "seed": seed,
        "turns": total_turns,
        "name": scenario.name,
        "language": scenario.language(),
        # The data and the rules both travel inside the transcript, so a
        # replay needs nothing but this one file.
        "scenario": scenario.data,
        "rules_source": scenario.rules_source,
    }
    if scenario.regions is not None:
        # The polygons, label points and computed adjacency the run was played on,
        # so the viewer draws the map from the transcript alone.
        header["regions"] = scenario.regions
    transcript.write(header)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_engine.py tests/test_bundle.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/casus/engine.py tests/test_engine.py tests/test_bundle.py
git commit -m "feat(engine): the scenario record carries the regions the run used"
```

---

### Task 9: The viewer fills the regions

**Files:**
- Modify: `ui/js/map.js`
- Modify: `tests/browser/browser_support.py`
- Test: `tests/browser/test_viewer.py`

**Interfaces:**
- Consumes: `run.header.regions` (the `scenario` record's `regions` key, as `RunModel.push`
  stores the record in `run.header`), `Casus.records.actorIds`, `Casus.records.label`.
- Produces: `Casus.map.draw(svg, run, snapshot, opts)` with the same signature and options as
  slice 1. When `run.header.regions` exists it draws the theatre's land outline, then one
  `<path class="region" data-region="<id>" data-kind="<kind>">` per region: filled with the
  holder's colour at a per-region shade, sea zones with `fill="transparent"` and a dashed outline
  in the holder's colour. When `opts.ctx` is set, each region path sits in
  `<g class="pl" data-place="<id>">`, so the whole region is the hover target through slice 1's
  card mechanism. The marker, the label, the ring gauge and the target rings sit at the region's
  label point. Without regions it draws dots, exactly as slice 1 does. `Casus.map.hasMap(run)`
  is true when the run has regions or any place has lat/lon.
- Produces in `tests/browser/browser_support.py`: `with_square_regions(records, size=1.0)
  -> list[dict]`.

- [ ] **Step 1: Add the fixture helper**

In `tests/browser/browser_support.py`, add `import copy` to the imports and append:

```python
def with_square_regions(records: list[dict], size: float = 1.0) -> list[dict]:
    """The same run with a `regions` key on its scenario record: a square of
    `size` degrees around each place's lat/lon, the sea place a sea zone. Written
    by hand, so the browser suite needs neither shapely nor the map data."""
    header = copy.deepcopy(records[0])
    places, lons, lats = {}, [], []
    half = size / 2
    for place_id, place in header["scenario"]["places"].items():
        lat, lon = place["attrs"]["lat"], place["attrs"]["lon"]
        ring = [
            [lon - half, lat - half],
            [lon + half, lat - half],
            [lon + half, lat + half],
            [lon - half, lat + half],
            [lon - half, lat - half],
        ]
        kind = "sea" if place["attrs"].get("terrain") == "sea" else "provinces"
        places[place_id] = {"polygon": [[ring]], "label": [lon, lat], "kind": kind}
        lons += [lon - half, lon + half]
        lats += [lat - half, lat + half]
    header["regions"] = {
        "version": 1,
        "mapdata": "squares",
        "digest": "",
        "theatre": [min(lons) - 1, min(lats) - 1, max(lons) + 1, max(lats) + 1],
        "land": [p["polygon"][0] for p in places.values() if p["kind"] != "sea"],
        "places": places,
        "adjacency": {
            place_id: list(place.get("adjacency") or [])
            for place_id, place in header["scenario"]["places"].items()
        },
    }
    return [header, *records[1:]]
```

- [ ] **Step 2: Write the failing browser tests**

Append to `tests/browser/test_viewer.py`, and add `with_square_regions` to its
`browser_support` import:

```python
def test_regions_fill_the_map_when_the_run_carries_them(page, bundle_url, tmp_path):
    records = with_square_regions(run_records(tmp_path))
    page.goto(bundle_url(records))
    count = len(records[0]["regions"]["places"])
    assert page.locator("#boardmap path.region").count() == count
    sea = page.locator('#boardmap path.region[data-kind="sea"]')
    assert sea.count() == 1 and sea.get_attribute("fill") == "transparent"
    capital = page.locator('#boardmap path.region[data-region="g-capital"]')
    assert capital.get_attribute("fill") not in ("transparent", "none")
    box = capital.bounding_box()
    assert box["width"] > 5 and box["height"] > 5


def test_a_run_without_regions_still_draws_dots(page, bundle_url, tmp_path):
    page.goto(bundle_url(run_records(tmp_path)))
    assert page.locator("#boardmap path.region").count() == 0
    assert page.locator("#boardmap circle.mk").count() == 4


def test_anywhere_in_a_region_shows_its_card(page, bundle_url, tmp_path):
    """The whole region is the hover target, not only the marker at its label."""
    records = with_square_regions(run_records(tmp_path))
    page.goto(bundle_url(records))
    box = page.locator('#boardmap path.region[data-region="g-interior"]').bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.1, box["y"] + box["height"] * 0.1)
    assert page.locator("#tip").is_visible()
    name = records[0]["scenario"]["places"]["g-interior"]["name"]
    assert name in page.locator("#tip").inner_text()


def test_the_distress_ring_stays_a_gauge_beside_the_label(page, bundle_url, tmp_path):
    """The fill means who holds a region. Distress is a gauge, never the fill."""
    records = with_square_regions(run_records(tmp_path))
    first = next(r for r in records if r["kind"] == "state")
    first["state"]["places"]["g-capital"]["attrs"]["civilian_distress"] = 40.0
    page.goto(bundle_url(records))
    assert page.locator('#boardmap circle[stroke="#ff8a9b"]').count() == 1
    capital = page.locator('#boardmap path.region[data-region="g-capital"]')
    assert capital.get_attribute("fill") != "#ff8a9b"


def test_every_beat_renders_with_regions(page, bundle_url, tmp_path):
    page.goto(bundle_url(with_square_regions(run_records(tmp_path))))
    for name in ("thinking", "declaring", "resolving", "dispatch"):
        step_to(page, 1, name)
        assert page.locator("#stage").bounding_box()["height"] > 200
    assert page.locator("#bigmap path.region").count() == 4
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/browser/test_viewer.py -q -k "region or ring"`
Expected: FAIL, e.g. `assert 0 == 4` for the `path.region` count.
`test_a_run_without_regions_still_draws_dots` passes already; it guards slice 1's behaviour.

- [ ] **Step 4: Implement**

Replace `ui/js/map.js` with the following. Against slice 1 it adds `regions`, `anchor`,
`holder`, `pathOf`, `shades` and `regionLayer`; changes `hasMap` and `box`; and makes `draw` put
markers, edges and labels at `anchor(run, id)` instead of `coords(p)`. The dot drawing is
otherwise unchanged.

```js
// The theatre. A run whose scenario record carries regions is drawn as territory:
// each region filled with its holder's colour, sea zones outlined, the land outline
// for context. A run without them is drawn as dots from each place's lat/lon over
// the world outline. Both share one equirectangular projection, so a place with no
// polygon still gets its dot among the regions.
(function () {
  const C = (window.Casus = window.Casus || {});
  const PALETTE = ["#4fa3ff", "#ff5a6e", "#a98bff", "#f5c451", "#4fd1b5", "#ff9e5e", "#7ee081", "#e07ee0"];
  // Fill opacities. Neighbours with one holder take different ones, so a border
  // between two of one country's regions still reads as a border.
  const SHADES = [0.55, 0.36, 0.47, 0.28, 0.63];
  const CTX = {}; let seq = 0;

  function colour(run, actorId) {
    const i = C.records.actorIds(run).indexOf(actorId);
    return i < 0 ? "#8a95a5" : PALETTE[i % PALETTE.length];
  }
  function places(run) { return run.scenario.places || {}; }
  function coords(p) {
    const a = p.attrs || {};
    return typeof a.lat === "number" && typeof a.lon === "number" ? [a.lon, a.lat] : null;
  }
  // The regions the run was played on: the scenario record's `regions` key.
  function regions(run) { return (run.header && run.header.regions) || null; }
  // Where a place's marker, label and gauge sit: its region's label point, else its lat/lon.
  function anchor(run, id) {
    const R = regions(run), r = R && R.places[id];
    return r ? r.label : coords(places(run)[id] || {});
  }
  function hasMap(run) { return !!regions(run) || Object.values(places(run)).some((p) => coords(p)); }

  function world() { return window.CASUS_WORLDMAP || { projection: { width: 1000, height: 500 }, countries: {} }; }
  function px(lon) { return ((lon + 180) / 360) * world().projection.width; }
  function py(lat) { return ((90 - lat) / 180) * world().projection.height; }

  function box(run, aspect) {
    const R = regions(run);
    let x0, x1, y0, y1;
    if (R) {
      const t = R.theatre;
      x0 = px(t[0]); x1 = px(t[2]); y0 = py(t[3]); y1 = py(t[1]);
    } else {
      const pts = Object.values(places(run)).map(coords).filter(Boolean);
      const xs = pts.map((c) => px(c[0])), ys = pts.map((c) => py(c[1]));
      x0 = Math.min(...xs) - 7; x1 = Math.max(...xs) + 7; y0 = Math.min(...ys) - 6; y1 = Math.max(...ys) + 6;
    }
    let w = x1 - x0, h = y1 - y0;
    if (w / h < aspect) { const nw = h * aspect; x0 -= (nw - w) / 2; w = nw; }
    else { const nh = w / aspect; y0 -= (nh - h) / 2; h = nh; }
    return { x: x0, y: y0, w, h };
  }

  function strengthAt(run, snap, placeId) {
    const size = ((run.scenario.display || {}).map || {}).size || "strength";
    return (snap.entities || []).filter((e) => e.place === placeId)
      .reduce((s, e) => s + Number((e.attrs || {})[size] || 0), 0);
  }

  function holder(run, snap, id) {
    const st = (snap.places || {})[id];
    return st ? st.owner || "" : (places(run)[id] || {}).owner || "";
  }
  function pathOf(multi) {
    return multi.map((poly) => poly.map((ring) =>
      "M" + ring.map((c) => px(c[0]).toFixed(3) + " " + py(c[1]).toFixed(3)).join("L") + "Z").join("")).join("");
  }
  function shades(run, snap, R) {
    const out = {};
    for (const id of Object.keys(R.places).sort()) {
      const own = holder(run, snap, id);
      const taken = new Set((R.adjacency[id] || [])
        .filter((q) => q in out && holder(run, snap, q) === own).map((q) => out[q]));
      const free = SHADES.findIndex((_, i) => !taken.has(i));
      out[id] = free < 0 ? 0 : free;
    }
    return out;
  }
  function regionLayer(run, snap, R, S, cid) {
    const shade = shades(run, snap, R);
    let o = `<path class="land" d="${pathOf(R.land)}" fill-rule="evenodd" stroke-width="${(0.12 * S).toFixed(3)}"/>`;
    for (const id of Object.keys(R.places).sort()) {
      const r = R.places[id], own = holder(run, snap, id), col = own ? colour(run, own) : "#8a95a5";
      const paint = r.kind === "sea"
        ? `fill="transparent" stroke="${col}" stroke-opacity="0.8" stroke-width="${(0.22 * S).toFixed(3)}" stroke-dasharray="${(0.8 * S).toFixed(3)} ${(0.5 * S).toFixed(3)}"`
        : `fill="${col}" fill-opacity="${r.kind === "site" ? 0.85 : SHADES[shade[id]]}" stroke="#f3e3e6" stroke-opacity="0.7" stroke-width="${(0.12 * S).toFixed(3)}"`;
      const path = `<path class="region" data-region="${esc(id)}" data-kind="${esc(r.kind)}" d="${pathOf(r.polygon)}" fill-rule="evenodd" ${paint}/>`;
      o += cid ? `<g class="pl" data-place="${esc(id)}">${path}</g>` : path;
    }
    return o;
  }

  function draw(svg, run, snap, opts) {
    opts = opts || {};
    if (!hasMap(run)) { svg.outerHTML = `<div class="nomap">${C.i18n.t("no_map")}</div>`; return; }
    const R = regions(run);
    const b = box(run, opts.aspect || 2), S = b.w / 100;
    const ring = ((run.scenario.display || {}).map || {}).ring;
    const cid = opts.ctx ? ++seq : 0;
    if (cid) CTX[cid] = Object.assign({ snapshot: snap }, opts.ctx);
    let o = "";
    if (R) o += regionLayer(run, snap, R, S, cid);
    else {
      for (const [iso, d] of Object.entries(world().countries || {})) {
        o += `<path class="land" d="${d}" stroke-width="${(0.12 * S).toFixed(3)}"/>`;
      }
    }
    if (opts.edges) {
      const seen = new Set();
      for (const [id, p] of Object.entries(places(run))) {
        for (const q of p.adjacency || []) {
          const k = [id, q].sort().join("|"), a = anchor(run, id), c = anchor(run, q);
          if (seen.has(k) || !a || !c) continue; seen.add(k);
          o += `<line class="edge" x1="${px(a[0])}" y1="${py(a[1])}" x2="${px(c[0])}" y2="${py(c[1])}" stroke-width="${0.18 * S}" stroke-dasharray="${0.6 * S} ${0.6 * S}"/>`;
        }
      }
    }
    let i = 0;
    for (const [id, p] of Object.entries(places(run))) {
      const c = anchor(run, id); if (!c) continue;
      const x = px(c[0]), y = py(c[1]);
      const st = (snap.places || {})[id] || { owner: p.owner, attrs: p.attrs || {} };
      const r = (0.8 + Math.sqrt(Math.max(strengthAt(run, snap, id), 0)) * 0.28) * S * (opts.rscale || 1);
      const fill = st.owner ? colour(run, st.owner) : "#5a626c";
      if (cid) o += `<g class="pl" data-place="${id}">`;
      const v = ring ? Number((st.attrs || {})[ring] || 0) : 0;
      if (v > 0) {
        const rr = r + 0.9 * S, circ = 2 * Math.PI * rr;
        o += `<circle cx="${x}" cy="${y}" r="${rr}" fill="none" stroke="#ff8a9b" stroke-width="${0.35 * S}" stroke-dasharray="${(Math.min(v, 100) / 100) * circ} ${circ}" transform="rotate(-90 ${x} ${y})"/>`;
      }
      for (const t of (opts.targets || []).filter((t) => t.place === id)) {
        o += `<circle class="target" cx="${x}" cy="${y}" r="${r + 1.4 * S}" stroke="${colour(run, t.actor)}" stroke-width="${0.4 * S}"/>`;
      }
      o += `<circle class="mk" cx="${x}" cy="${y}" r="${r}" fill="${fill}" stroke-width="${0.25 * S}"/>`;
      const flip = i++ % 2 === 1, fs = (opts.font || 1.9) * S;
      if (fs > 0) {
        o += `<text class="plabel" x="${flip ? x - r - S : x + r + S}" y="${y + fs * 0.35}" text-anchor="${flip ? "end" : "start"}" font-size="${fs}" stroke-width="${0.35 * S}">${esc(C.records.label(run, id))}</text>`;
      }
      if (cid) o += `<circle cx="${x}" cy="${y}" r="${r + 2.2 * S}" fill="transparent"/></g>`;
    }
    svg.setAttribute("viewBox", `${b.x} ${b.y} ${b.w} ${b.h}`);
    svg.setAttribute("preserveAspectRatio", `xMidYMid ${opts.slice ? "slice" : "meet"}`);
    if (cid) svg.dataset.ctx = String(cid); else delete svg.dataset.ctx;
    svg.innerHTML = o;
  }

  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }

  C.map = { draw, hasMap, colour, esc, context: (id) => CTX[id] || null };
})();
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/browser/test_viewer.py tests/test_ui_scripts.py -q`
Expected: PASS, slice 1's viewer tests included (a dot-only run must look exactly as before).

- [ ] **Step 6: Break it on purpose**

In `regionLayer`, change `o += cid ? \`<g class="pl" ...` so the path is never wrapped
(`o += path;`). Run `uv run pytest tests/browser/test_viewer.py -q -k anywhere_in_a_region`.
Expected: FAIL, `#tip` not visible. Revert.

- [ ] **Step 7: Commit**

```bash
git add ui/js/map.js tests/browser/browser_support.py tests/browser/test_viewer.py
git commit -m "feat(ui): fill map regions when the transcript carries them"
```

---

### Task 10: The Caribbean scenario as regions

The scenario is private. It lives in the vault and is committed in the Workspace repo, never
in casus. This task changes two casus tests first, so they keep meaning what they meant, then
migrates the scenario.

**Files:**
- Modify: `tests/reference/test_scenarios.py` (`test_adjacency_is_symmetric_in_every_scenario`),
  `tests/test_migration.py` (`without_recovery`)
- Modify (Workspace repo): `vault/Efforts/Areas/University/casus-clase/caribbean-2026/scenario.yaml`
- Create (Workspace repo): `vault/Efforts/Areas/University/casus-clase/caribbean-2026/regions.json`

**Interfaces:**
- Consumes: `casus regions`, `Scenario.load`, `Scenario.regions`.
- Produces: the Caribbean's eight places as regions; `tests/test_migration.py::v1_adjacency()
  -> dict[str, list[str]]`.

- [ ] **Step 1: Link the private scenarios into the worktree**

```bash
test -e scenarios/private || \
  ln -s /home/apiad/Workspace/vault/Efforts/Areas/University/casus-clase scenarios/private
```

The link is gitignored. Without it every step below that names `scenarios/private` skips or
fails.

- [ ] **Step 2: Read symmetry from the loaded state**

`test_adjacency_is_symmetric_in_every_scenario` iterates the raw YAML, where an exception block
`{add: [...]}` would read as neighbours named `add`. In `tests/reference/test_scenarios.py`,
replace it with:

```python
def test_adjacency_is_symmetric_in_every_scenario():
    """An asymmetric edge lets one side strike from cover, which is a modelling
    accident rather than a decision. Read from the loaded state, where computed
    adjacency and its exceptions have been applied."""
    for path in [SCENARIOS / "smoke", *_on_reference()]:
        places = Scenario.load(path, validate=False).initial_state().places
        for place_id, place in places.items():
            for neighbour in place.adjacency:
                back = places[neighbour].adjacency
                assert place_id in back, f"{path.name}: {place_id} -> {neighbour} is one-way"
```

- [ ] **Step 3: Hold the v1 reproduction to v1's map**

`test_the_ported_caribbean_reproduces_its_recorded_trajectory` compares each place's adjacency
list, in order, with v1's recording. After this task the scenario's adjacency is computed, and
it differs from v1's hand-written graph on purpose (Step 7). The acceptance test is about the
ruleset, so it plays on the graph v1 played on. In `tests/test_migration.py`, add `import copy`
and replace `without_recovery` with:

```python
def v1_adjacency() -> dict[str, list[str]]:
    """Each region's adjacency as v1 recorded it, in v1's order."""
    first = next(r for r in engine.read_records(REFERENCE_RUN) if r["kind"] == "state")
    return {rid: list(region["adjacency"]) for rid, region in first["state"]["regions"].items()}


def without_recovery() -> Scenario:
    """The Caribbean on the reference ruleset with the ratchet repair switched
    off and v1's adjacency restored: v1's physics on v1's map, which is what the
    recording can be held to. The scenario's own adjacency is computed from its
    regions and differs from v1's hand-written lists on purpose."""
    scenario = Scenario.load(CARIBBEAN, validate=False)
    source = scenario.rules_source
    for name in RECOVERY_RATES:
        line = next(ln for ln in source.splitlines() if ln.startswith(f"{name} = "))
        source = source.replace(line, f"{name} = 0.0")
    data = copy.deepcopy(scenario.data)
    for place_id, adjacency in v1_adjacency().items():
        data["places"][place_id]["adjacency"] = adjacency
    return Scenario.from_parts(data, source)
```

- [ ] **Step 4: Run both before migrating**

```bash
CASUS_REFERENCE_RUN=/home/apiad/Workspace/repos/casus/runs/caribbean-lingo-101.jsonl \
  uv run pytest tests/test_migration.py tests/reference/test_scenarios.py -q
```

Expected: PASS, with the migration tests running, not skipped (`-rs` shows no skip reasons for
`test_migration.py`). Both changes are no-ops on today's scenario.

Commit:

```bash
git add tests/reference/test_scenarios.py tests/test_migration.py
git commit -m "test: read adjacency from the loaded state; hold the v1 replay to v1's map"
```

- [ ] **Step 5: Save the hand-written graph**

The vault autosync timer may commit the scenario while you edit it, so save the graph now
rather than reading it from git later:

```bash
uv run python -c "import json, yaml; d = yaml.safe_load(open('scenarios/private/caribbean-2026/scenario.yaml')); json.dump({p: s['adjacency'] for p, s in d['places'].items()}, open('/tmp/caribbean-hand-adjacency.json', 'w'), indent=1)"
cat /tmp/caribbean-hand-adjacency.json
```

Expected: eight places, `cu-habana: [cu-occidente, str-florida]` among them.

- [ ] **Step 6: Write the region blocks**

In `scenarios/private/caribbean-2026/scenario.yaml`, replace each place's `adjacency:` key and
the `- ...` lines under it with the lines below, leaving `name`, `owner`, `attrs` and `source`
where they are. Keep every other key: `lat`/`lon` stay, because the region findings check
them and slice 1's dots and `tests/test_worldmap.py` read them.

```yaml
  cu-habana:
    region: {provinces: [CU-03, CU-16]}
  cu-occidente:
    region: {provinces: [CU-01, CU-15, CU-99]}
  cu-centro:
    region: {provinces: [CU-04, CU-05, CU-06, CU-07, CU-08, CU-09]}
  cu-oriente:
    # Natural Earth draws the Guantánamo naval base as its own unit with no
    # country (-99-X13~). Naming it here gives the gtmo site a region to be
    # carved from; without it the site falls on land that is no place.
    region: {provinces: [CU-10, CU-11, CU-12, CU-13, CU-14, "-99-X13~"]}
  gtmo:
    region: {site: [19.90, -75.13], radius_km: 15}
  us-florida:
    region: {provinces: [US-FL]}
  str-florida:
    region: {sea: [24.2, -81.3], reach_km: 240}
    # The sea lanes round either end of Cuba. The two zones' reaches do not
    # meet (seeds about 560 km apart, reaches 240 + 300 km), so geometry cannot
    # see the link v1's authors drew.
    adjacency: {add: [car-north]}
  car-north:
    region: {sea: [20.5, -77.5], reach_km: 300}
```

`car-north` reaches 300 km, not the spec example's 240, so that it covers the water off
Guantánamo Bay (256 km from its seed) and the `gtmo` site touches it.

Add to the `display` block:

```yaml
  # The computed theatre, [-88.6, 16.8, -73.1, 32.0], shows the whole Florida
  # panhandle and more of the Gulf than of Cuba. This keeps the room on Cuba and
  # the straits; the adjacency is the same either way (measured 2026-09-29).
  theatre: [-86.0, 18.5, -73.5, 28.0]
```

- [ ] **Step 7: Compute the regions and compare with the hand-written graph**

Run: `uv run casus regions scenarios/private/caribbean-2026`
Expected: exit 0, one adjacency line per place, then
`casus: wrote scenarios/private/caribbean-2026/regions.json — 8 regions, 70 KiB` (give or take
a KiB).

Then print each difference, for the computed graph and for the graph the engine uses after the
exception:

```bash
uv run python - <<'EOF'
import json
from casus.scenario import Scenario
hand = {p: set(v) for p, v in json.load(open("/tmp/caribbean-hand-adjacency.json")).items()}
scenario = Scenario.load("scenarios/private/caribbean-2026", validate=False)
computed = {p: set(v) for p, v in scenario.regions["adjacency"].items()}
used = {p: set(place.adjacency) for p, place in scenario.initial_state().places.items()}
for p in sorted(hand):
    print(f"{p:13} computed +{sorted(computed[p] - hand[p])} -{sorted(hand[p] - computed[p])}"
          f"   used +{sorted(used[p] - hand[p])} -{sorted(hand[p] - used[p])}")
EOF
```

Expected, as measured on 2026-09-29:

```
car-north     computed +[] -['str-florida']   used +[] -[]
cu-centro     computed +['cu-habana', 'str-florida'] -['cu-occidente']   used +['cu-habana', 'str-florida'] -['cu-occidente']
cu-habana     computed +['cu-centro'] -[]   used +['cu-centro'] -[]
cu-occidente  computed +[] -['cu-centro']   used +[] -['cu-centro']
cu-oriente    computed +[] -[]   used +[] -[]
gtmo          computed +[] -[]   used +[] -[]
str-florida   computed +['cu-centro'] -['car-north']   used +['cu-centro'] -[]
us-florida    computed +[] -[]   used +[] -[]
```

If a line differs from this table, stop: a block or the map data changed, and every new line
needs its own explanation below before the PR opens. Each difference in the table goes into the
PR body with its reason:

| edge | computed | used | why |
|---|---|---|---|
| cu-habana – cu-centro | added | added | Mayabeque (CU-16) is part of cu-habana now, and it borders Matanzas (CU-04). v1 treated Havana as the city and ran the land route through Western Cuba. |
| cu-occidente – cu-centro | removed | removed | Same cause: Artemisa and Pinar del Río do not touch Matanzas; Mayabeque lies between them. |
| cu-centro – str-florida | added | added | Matanzas' north coast (Varadero, Cárdenas) lies within the straits zone's 240 km. |
| str-florida – car-north | removed | kept | The zones' reaches do not meet; the `add` exception keeps v1's sea lane round Cuba. |

The three edges the class scenario now plays differently are a modelling change. Alex decides
in review whether to keep them or restore v1's graph with exceptions (`cu-occidente:
adjacency: {add: [cu-centro]}` and so on).

- [ ] **Step 8: Validate and run the suites that read the scenario**

```bash
uv run casus validate scenarios/private/caribbean-2026
CASUS_REFERENCE_RUN=/home/apiad/Workspace/repos/casus/runs/caribbean-lingo-101.jsonl \
  uv run pytest tests/test_migration.py tests/reference tests/test_worldmap.py -q -rs
```

Expected: `casus: scenarios/private/caribbean-2026: no findings` with no `warning:` lines, and
PASS with no skips in `test_migration.py`. Read the exit codes directly, not through a pipe.

Break it on purpose: delete the two lines in `without_recovery` that restore `v1_adjacency()`
and rerun `test_migration.py`. Expected: FAIL with `turn 1: place.cu-centro.adjacency recorded
['cu-occidente', 'cu-oriente', 'car-north'], port gives ['car-north', 'cu-habana', 'cu-oriente',
'str-florida']`. Restore the lines.

- [ ] **Step 9: Commit in the Workspace repo**

```bash
git -C /home/apiad/Workspace add \
  vault/Efforts/Areas/University/casus-clase/caribbean-2026/scenario.yaml \
  vault/Efforts/Areas/University/casus-clase/caribbean-2026/regions.json
git -C /home/apiad/Workspace commit -m "feat(casus-clase): Caribbean places as regions, adjacency computed"
```

If the autosync timer committed the files first, `git -C /home/apiad/Workspace log -1 --
vault/Efforts/Areas/University/casus-clase/caribbean-2026/regions.json` shows it and there is
nothing left to commit. Push the Workspace repo.

---

### Task 11: Docs, status, and the acceptance check

**Files:**
- Modify: `README.md`, `AGENTS.md`, `scenarios/README.md`,
  `docs/specs/2026-09-29-map-regions-design.md` (status header),
  `docs/plans/2026-09-29-casus-app-plan.md` (the slice table's PR number, as "After each slice"
  asks)

- [ ] **Step 1: README**

Under "Install and run", after the block that ends with `casus bundle`, add:

````markdown
A place can be a territory rather than a point. Its `region` block names
provinces (`{provinces: [CU-03, CU-16]}`), a country (`{country: HT}`), a sea
zone (`{sea: [lat, lon], reach_km: 240}`) or a site
(`{site: [lat, lon], radius_km: 15}`). After editing one, compute the polygons
and the adjacency once:

```bash
uv run casus regions scenarios/<name>    # writes scenarios/<name>/regions.json
```

Running, replaying and bundling read `regions.json` and need no map data. The
map is Natural Earth's Admin 1 at 1:10m, public domain, shipped in the package.
````

Add one row to the module table:

```markdown
| `geo/` | Map regions: the packaged provinces, polygons and adjacency for `casus regions` |
```

- [ ] **Step 2: scenarios/README.md**

Append to "Writing one":

```markdown
Places can carry a `region` block instead of hand-written adjacency. Places on
the same provinces or country split them by Voronoi, so each needs a `seed:
[lat, lon]`. Adjacency is computed from shared borders and coasts; write only
the exceptions, `adjacency: {add: [...], remove: [...]}`, and they apply at both
ends. Run `casus regions <dir>` after every change to a region block: a scenario
whose `regions.json` is older than its blocks does not load, and the error names
that command. The spec, with every rule and finding, is
`docs/specs/2026-09-29-map-regions-design.md`.
```

- [ ] **Step 3: AGENTS.md**

Under "Where everything lives", after the `src/casus/` line, add:

```markdown
- `src/casus/geo/` — map regions. `mapdata.py` reads the packaged
  `src/casus/data/admin1.json.xz`, `regions.py` computes polygons and adjacency
  for `casus regions`. Nothing else imports them: running, replaying and
  bundling read `regions.json` and never load shapely, and a test enforces it.
```

and change the `tools/` line to:

```markdown
- `tools/` — one-shot generators (`build_worldmap.py`, `build_mapdata.py`). Their
  output is committed; they are not imported.
```

Under "What done means", add:

```markdown
- Bundle a run of a scenario with regions and look at it: each region filled in
  its holder's colour, sea zones outlined, the hover card on any point of a
  region.
```

- [ ] **Step 4: Spec status and the master plan's slice table**

In `docs/specs/2026-09-29-map-regions-design.md` frontmatter, set
`status: "implemented in slice 2 (PR #<n>)"`. In `docs/plans/2026-09-29-casus-app-plan.md`,
add the PR number to slice 2's row.

- [ ] **Step 5: Acceptance, the way a person does it**

With the endpoint configured (`BASE_URL`, `API_KEY`):

```bash
uv run casus run scenarios/private/caribbean-2026 --seed 101 --turns 2 --out /tmp/caribbean-regions-101.jsonl
uv run casus verify /tmp/caribbean-regions-101.jsonl
uv run casus bundle /tmp/caribbean-regions-101.jsonl --out /tmp/caribe-regions.html
```

Expected: `replay OK — 2 turns, every state digest matches`, and the bundle's size printed.

Open `/tmp/caribe-regions.html` from the file manager, not through a server. Check, and write in
the PR body what you saw:

- Cuba fills in Cuba's colour, four regions in visibly different shades, with light borders
  between them. Florida below 28°N fills in the United States' colour. The Guantánamo disc is a
  small, strongly filled circle on the south-east coast.
- The Straits of Florida and the Northern Caribbean are dashed outlines, not fills.
- Hovering anywhere in Oriente, far from its label, shows the card, and its borders line lists
  Centro, Guantánamo and Caribe norte.
- The distress gauge sits by each label, and the region fill does not change with distress.
- In the command post, after resolution, a region that changed hands changes colour.

Then `uv run casus serve`, open the same run from the home page, and step the same turns. Both
must look the same.

- [ ] **Step 6: Commit and open the PR**

```bash
git add README.md AGENTS.md scenarios/README.md docs/specs/2026-09-29-map-regions-design.md \
  docs/plans/2026-09-29-casus-app-plan.md
git commit -m "docs: map regions, casus regions, and how to check them"
git push -u origin 5-slice-2-map-regions
gh pr create --title "feat: map regions, computed adjacency, and the viewer fills them" \
  --body "Part of #5. ..."
```

The PR body carries: the adjacency table from Task 10 Step 7 with its reasons, the note that
three class-scenario edges change and that Alex decides on them, the `-99-X13~` addition to
Oriente and why, the acceptance notes from Step 5 (what was checked and on which run), and the
contract changes below.

---

## Contract changes needed

> Applied during plan review (2026-09-29) to the master plan's "Amendments from the slice plans" section, resolved against the other slices. Do not edit the master plan again for these; if the code must differ from the amendments, change the amendments in this slice's PR.

The master plan says a slice may not change what it names without changing it in the same PR.
These are the changes this slice needs. The PR that implements the slice edits the master plan
to match.

1. **The viewer reads regions from `run.header.regions`, not `run.scenario.regions`.** The
   Python contract puts `regions` at the top level of the `scenario` record, and slice 1's
   `RunModel.push` stores that record as `run.header` and its `scenario` key (the scenario's
   data) as `run.scenario`. The JS comment in "JavaScript interfaces" should read "slice 2: draws
   filled regions when `run.header.regions` exists, dots otherwise".
2. **`region_digest(places, theatre=None)`.** The digest also covers `display.theatre`, because
   the theatre changes the geometry (the sea base, the clipping). A digest over the places alone
   would let a scenario with an edited theatre play a stale map.
3. **`Regions` gains `mapdata: str = ""`**, the map data version that `to_json` writes into
   `regions.json`'s `mapdata` key.
4. **A new file, `src/casus/geo/digest.py`.** `region_digest` lives there and `geo/regions.py`
   re-exports it under the name the master plan gives. `Scenario.load` imports the digest
   without importing shapely, which the spec requires ("running, replaying and bundling one need
   neither the map data nor shapely").
5. **Slice 2 also modifies `engine.py`, `server/app.py`, `tests/helpers.py`,
   `tests/test_migration.py` and `tests/reference/test_scenarios.py`,** which the file table does
   not list for it. `engine.py` writes the `regions` key, as the contracts section already says.
   `server/app.py`'s `_card` reads counts from the YAML, so a stale map shows as an invalid
   scenario instead of failing the home page. The two tests are adjusted as Task 10 explains.
6. **`Scenario` gains `regions` and `warnings`, and `casus validate` prints warnings without
   failing.** The master plan does not name them. Slice 6's `Workspace.write` should report
   `regions.compute` findings and these warnings among its own findings.
