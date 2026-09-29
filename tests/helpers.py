"""Shared state builders.

Every helper here builds state from the module's own constants rather than from
literals repeated in the assertions, so a test cannot pass by agreeing with
itself.
"""

from __future__ import annotations

import json
import pathlib

import yaml
from v1shape import ActorState, Force, RegionState, WorldState

from casus.geo.digest import region_digest


def make_actor(actor_id: str, **overrides) -> ActorState:
    base = dict(
        id=actor_id,
        name=actor_id,
        fuel_days=60.0,
        munitions=80.0,
        political_capital=70.0,
        domestic_support=70.0,
        intl_legitimacy=60.0,
        isr=0.8,
        fuel_inflow=4.0,
        escalation_rung=0,
    )
    base.update(overrides)
    return ActorState(**base)


def make_region(region_id: str, owner: str, **overrides) -> RegionState:
    base = dict(
        id=region_id,
        name=region_id,
        owner=owner,
        adjacency=(),
        centroid=(23.1, -82.4),
        control=100.0,
        infrastructure=100.0,
        civilian_distress=0.0,
        population=1_000_000,
        terrain="coastal",
        country=owner,
    )
    base.update(overrides)
    return RegionState(**base)


def make_force(owner: str, kind: str, **overrides) -> Force:
    base = dict(
        id=f"{owner}-{kind}-1",
        owner=owner,
        kind=kind,
        strength=50.0,
        readiness=0.9,
        region="r1",
        posture="garrison",
    )
    base.update(overrides)
    return Force(**base)


def make_world(
    actors: dict[str, ActorState] | None = None,
    regions: dict[str, RegionState] | None = None,
    forces: tuple[Force, ...] = (),
    turn: int = 1,
    relations: dict[str, int] | None = None,
) -> WorldState:
    actors = actors or {"ATK": make_actor("ATK"), "DEF": make_actor("DEF")}
    regions = regions or {
        "r1": make_region("r1", "DEF"),
        "sea-1": make_region("sea-1", "", terrain="sea", population=0),
    }
    return WorldState(
        turn=turn,
        actors=actors,
        regions=regions,
        forces=forces,
        relations=relations or {"ATK>DEF": -60, "DEF>ATK": -60},
    )


class FakeEngine:
    """Stands in for a lingo Engine in tests.

    Validates a canned payload against whatever schema the caller asks for, so a
    test that hands it an impossible declaration fails the same way the real
    provider would, rather than sliding through.
    """

    def __init__(self, reply=None):
        self.reply = (
            reply
            if reply is not None
            else {
                "actions": [{"type": "hold"}],
                "rationale": "wait",
                "assessment": "they wait too",
            }
        )
        self.prompts: list[str] = []
        self.schemas: list[type] = []

    async def create(self, context, schema, *instructions):
        prompt = context.messages[-1].content
        self.prompts.append(prompt)
        self.schemas.append(schema)
        payload = self.reply(prompt) if callable(self.reply) else self.reply
        return schema.model_validate(payload)


def scripted(per_actor: dict[str, dict] | None = None, default: dict | None = None):
    """A reply function keyed on the actor named in the prompt."""
    per_actor = per_actor or {}
    fallback = default or {
        "actions": [{"type": "hold"}],
        "rationale": "wait",
        "assessment": "nothing",
    }

    def reply(prompt: str) -> dict:
        actor = prompt.split("You are ")[1].split("(")[1].split(")")[0]
        return per_actor.get(actor, fallback)

    return reply


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
