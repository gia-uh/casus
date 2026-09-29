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
