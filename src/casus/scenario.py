"""Scenarios are YAML data, never code.

A scenario names the actors, their private briefings, the model each one plays
with, the map, and the starting order of battle. It is validated on load, because
a typo in a region identifier should fail at the door rather than surface as a
rejected action on turn four.
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Any

import yaml

from .state import ActorState, Force, RegionState, WorldState

TERRAINS = frozenset({"urban", "rural", "coastal", "sea"})
FORCE_KINDS = frozenset({"ground", "air", "naval", "air_defense", "irregular"})
POSTURES = frozenset({"garrison", "offensive", "defensive", "dispersed", "hardened"})


class ScenarioError(ValueError):
    """The scenario file does not describe a usable world."""


@dataclasses.dataclass(frozen=True)
class Scenario:
    name: str
    turns: int
    description: str
    actors: dict[str, dict[str, Any]]
    regions: dict[str, dict[str, Any]]
    forces: tuple[dict[str, Any], ...]
    relations: dict[str, int]
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: str | pathlib.Path) -> Scenario:
        text = pathlib.Path(path).read_text()
        return cls.from_yaml(text)

    @classmethod
    def from_yaml(cls, text: str) -> Scenario:
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ScenarioError("a scenario file must contain a mapping")
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scenario:
        for key in ("name", "actors", "regions"):
            if key not in data:
                raise ScenarioError(f"scenario is missing '{key}'")

        actors = dict(data["actors"])
        regions = dict(data["regions"])
        forces = tuple(data.get("forces") or ())

        for region_id, region in regions.items():
            terrain = region.get("terrain")
            if terrain not in TERRAINS:
                raise ScenarioError(f"region '{region_id}' has unknown terrain '{terrain}'")
            owner = region.get("owner") or ""
            if owner and owner not in actors:
                raise ScenarioError(f"region '{region_id}' is owned by unknown actor '{owner}'")
            for neighbour in region.get("adjacency") or ():
                if neighbour not in regions:
                    raise ScenarioError(
                        f"region '{region_id}' is adjacent to unknown region '{neighbour}'"
                    )

        seen_ids: set[str] = set()
        for force in forces:
            force_id = force.get("id", "<unnamed>")
            if force_id in seen_ids:
                raise ScenarioError(f"duplicate force id '{force_id}'")
            seen_ids.add(force_id)
            if force.get("owner") not in actors:
                raise ScenarioError(
                    f"force '{force_id}' has unknown owner '{force.get('owner')}'"
                )
            if force.get("region") not in regions:
                raise ScenarioError(
                    f"force '{force_id}' is in unknown region '{force.get('region')}'"
                )
            if force.get("kind") not in FORCE_KINDS:
                raise ScenarioError(
                    f"force '{force_id}' has unknown kind '{force.get('kind')}'"
                )
            if force.get("posture", "garrison") not in POSTURES:
                raise ScenarioError(
                    f"force '{force_id}' has unknown posture '{force.get('posture')}'"
                )

        for actor_id, actor in actors.items():
            if not actor.get("briefing"):
                raise ScenarioError(f"actor '{actor_id}' has no briefing")
            if not actor.get("model"):
                raise ScenarioError(f"actor '{actor_id}' has no model")

        return cls(
            name=str(data["name"]),
            turns=int(data.get("turns", 6)),
            description=str(data.get("description", "")),
            actors=actors,
            regions=regions,
            forces=forces,
            relations={str(k): int(v) for k, v in (data.get("relations") or {}).items()},
            raw=data,
        )

    def initial_state(self) -> WorldState:
        return WorldState(
            turn=1,
            actors={
                actor_id: ActorState(
                    id=actor_id,
                    name=str(spec.get("name", actor_id)),
                    fuel_days=float(spec.get("fuel_days", 60)),
                    munitions=float(spec.get("munitions", 80)),
                    political_capital=float(spec.get("political_capital", 70)),
                    domestic_support=float(spec.get("domestic_support", 70)),
                    intl_legitimacy=float(spec.get("intl_legitimacy", 60)),
                    isr=float(spec.get("isr", 0.6)),
                    fuel_inflow=float(spec.get("fuel_inflow", 0)),
                )
                for actor_id, spec in self.actors.items()
            },
            regions={
                region_id: RegionState(
                    id=region_id,
                    name=str(spec.get("name", region_id)),
                    owner=str(spec.get("owner") or ""),
                    adjacency=tuple(spec.get("adjacency") or ()),
                    centroid=(
                        float((spec.get("centroid") or (0, 0))[0]),
                        float((spec.get("centroid") or (0, 0))[1]),
                    ),
                    control=float(spec.get("control", 100)),
                    infrastructure=float(spec.get("infrastructure", 100)),
                    civilian_distress=float(spec.get("civilian_distress", 0)),
                    population=int(spec.get("population", 0)),
                    terrain=str(spec["terrain"]),
                    country=str(spec.get("country") or spec.get("owner") or ""),
                )
                for region_id, spec in self.regions.items()
            },
            forces=tuple(
                Force(
                    id=str(spec["id"]),
                    owner=str(spec["owner"]),
                    kind=str(spec["kind"]),
                    strength=float(spec["strength"]),
                    readiness=float(spec.get("readiness", 0.9)),
                    region=str(spec["region"]),
                    posture=str(spec.get("posture", "garrison")),
                )
                for spec in self.forces
            ),
            relations=dict(self.relations),
        )

    def briefing(self, actor_id: str) -> str:
        return str(self.actors[actor_id]["briefing"])

    def narrator_model(self) -> str:
        """Model for the news ticker. Empty means the endpoint's default."""
        return str(self.raw.get("narrator_model", "") or "")

    def model(self, actor_id: str) -> str:
        return str(self.actors[actor_id]["model"])

    def country_codes(self) -> tuple[str, ...]:
        codes = {
            str(region.get("country") or region.get("owner") or "")
            for region in self.regions.values()
        }
        return tuple(sorted(c for c in codes if c))
