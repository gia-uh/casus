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
        str(place_id): _keyed(spec["region"])
        for place_id, spec in places.items()
        if isinstance(spec, dict) and "region" in spec
    }
    canonical = json.dumps(
        {"places": blocks, "theatre": theatre},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _keyed(value: object) -> object:
    """Every mapping key as a string, so json can sort keys YAML read as ints."""
    if isinstance(value, dict):
        return {str(k): _keyed(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_keyed(v) for v in value]
    return value
