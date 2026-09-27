#!/usr/bin/env python3
"""Turn Natural Earth country boundaries into `ui/worldmap.json`.

A one-shot generator. Its output is committed; nothing imports this file. Run it
again only to change the projection or the simplification tolerance.

    curl -sL -o .cache/ne_110m_admin_0.geojson \\
      https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson
    uv run python tools/build_worldmap.py

Source: Natural Earth, Admin 0 Countries at 1:110m, public domain.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

#: Douglas-Peucker here is recursive, and the largest Natural Earth rings are
#: deep enough to exceed CPython's default 1000-frame limit. Raising it inside
#: the tool keeps `uv run python tools/build_worldmap.py` working plainly.
sys.setrecursionlimit(50_000)

#: SVG viewBox. 2:1 matches an equirectangular projection of the whole globe.
WIDTH, HEIGHT = 1000.0, 500.0

#: Douglas-Peucker tolerance in degrees. At 110m source resolution this keeps
#: Cuba recognisable while cutting the payload to something a single HTML file
#: can carry comfortably.
TOLERANCE = 0.12

#: Rings smaller than this in projected area are dropped: at world scale they are
#: sub-pixel specks that cost bytes and render as dirt.
MIN_RING_AREA = 0.5


def project(lon: float, lat: float) -> tuple[float, float]:
    """Equirectangular. Straightforward, and the centroids in the scenarios are
    lat/lon pairs, so the replayer can place a marker with the same two lines."""
    x = (lon + 180.0) / 360.0 * WIDTH
    y = (90.0 - lat) / 180.0 * HEIGHT
    return round(x, 2), round(y, 2)


def simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas-Peucker on lat/lon, before projection."""
    if len(points) < 3:
        return points
    first, last = points[0], points[-1]
    index, worst = 0, 0.0
    for i in range(1, len(points) - 1):
        distance = _perpendicular_distance(points[i], first, last)
        if distance > worst:
            index, worst = i, distance
    if worst <= tolerance:
        return [first, last]
    left = simplify(points[: index + 1], tolerance)
    right = simplify(points[index:], tolerance)
    return left[:-1] + right


def _perpendicular_distance(point, start, end) -> float:
    (px, py), (x1, y1), (x2, y2) = point, start, end
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    cx, cy = x1 + t * dx, y1 + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def ring_area(ring: list[tuple[float, float]]) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def rings_of(geometry: dict) -> list[list[tuple[float, float]]]:
    kind = geometry["type"]
    if kind == "Polygon":
        return [[(x, y) for x, y in ring] for ring in geometry["coordinates"]]
    if kind == "MultiPolygon":
        return [
            [(x, y) for x, y in ring]
            for polygon in geometry["coordinates"]
            for ring in polygon
        ]
    return []


def path_for(geometry: dict, tolerance: float) -> str:
    commands: list[str] = []
    for ring in rings_of(geometry):
        thinned = simplify(ring, tolerance)
        if len(thinned) < 3:
            continue
        projected = [project(lon, lat) for lon, lat in thinned]
        if ring_area(projected) < MIN_RING_AREA:
            continue
        head, *tail = projected
        commands.append(
            "M" + f"{head[0]} {head[1]}" + "".join(f"L{x} {y}" for x, y in tail) + "Z"
        )
    return "".join(commands)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=".cache/ne_110m_admin_0.geojson")
    parser.add_argument("--out", default="ui/worldmap.json")
    parser.add_argument("--tolerance", type=float, default=TOLERANCE)
    args = parser.parse_args()

    data = json.loads(pathlib.Path(args.source).read_text())
    countries: dict[str, str] = {}
    names: dict[str, str] = {}
    for feature in data["features"]:
        props = feature["properties"]
        iso = props.get("ISO_A2_EH") or props.get("ISO_A2") or ""
        if not iso or iso == "-99":
            continue
        path = path_for(feature["geometry"], args.tolerance)
        if not path:
            continue
        countries[iso] = path
        names[iso] = props.get("NAME") or iso

    payload = {
        "projection": {"kind": "equirectangular", "width": WIDTH, "height": HEIGHT},
        "source": "Natural Earth Admin 0 Countries 1:110m (public domain)",
        "tolerance": args.tolerance,
        "countries": countries,
        "names": names,
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")))
    size = out.stat().st_size
    print(f"wrote {out} — {len(countries)} countries, {size / 1024:.0f} KiB")
    print(f"Cuba path length: {len(countries.get('CU', ''))} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
