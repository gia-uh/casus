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
import itertools
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
            for (x0, y0), (x1, y1) in itertools.pairwise(points):
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

    today = datetime.datetime.now(datetime.UTC).date().isoformat()
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
