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
