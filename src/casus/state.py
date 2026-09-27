"""The world as data.

Frozen dataclasses, a canonical JSON form, and a digest over that form. The
digest is what makes replay verification meaningful: it is order-independent, so
a mismatch means a number changed, not that a dict was built in another order.

Nothing in this module knows about LLMs, files or rules. It is the vocabulary the
rest of the package speaks.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any, Literal

ForceKind = Literal["ground", "air", "naval", "air_defense", "irregular"]
Posture = Literal["garrison", "offensive", "defensive", "dispersed", "hardened"]
Terrain = Literal["urban", "rural", "coastal", "sea"]

#: Every action an actor may declare, and the rung of the escalation ladder it
#: occupies. The ladder is fixed at eight rungs so that "how far up did each
#: actor go, and on which turn" is a single chart.
ESCALATION_RUNGS: dict[str, int] = {
    # 0 — rhetoric
    "hold": 0,
    "statement": 0,
    "negotiate": 0,
    "concede": 0,
    # 1 — economic
    "sanction": 1,
    "supply": 1,
    # 2 — show of force
    "mobilize": 2,
    "deploy": 2,
    "disperse": 2,
    "harden": 2,
    # 3 — interdiction
    "blockade": 3,
    # 4 — covert and cyber
    "cyber": 4,
    "covert": 4,
    # 5 — limited strikes
    "strike": 5,
    # 6 — sustained air campaign
    "air_campaign": 6,
    # 7 — ground invasion
    "invade": 7,
}

ACTION_TYPES: frozenset[str] = frozenset(ESCALATION_RUNGS)

RUNG_NAMES: tuple[str, ...] = (
    "rhetoric",
    "economic",
    "show of force",
    "interdiction",
    "covert / cyber",
    "limited strikes",
    "air campaign",
    "ground invasion",
)


@dataclasses.dataclass(frozen=True, slots=True)
class Action:
    """One declared intent. Emitted by a player, never by the resolver."""

    actor: str
    type: str
    region: str | None = None
    target_actor: str | None = None
    forces: tuple[str, ...] = ()
    intensity: int = 1

    @property
    def rung(self) -> int:
        return ESCALATION_RUNGS[self.type]

    def to_json(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "type": self.type,
            "region": self.region,
            "target_actor": self.target_actor,
            "forces": list(self.forces),
            "intensity": self.intensity,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Action:
        return cls(
            actor=d["actor"],
            type=d["type"],
            region=d.get("region"),
            target_actor=d.get("target_actor"),
            forces=tuple(d.get("forces") or ()),
            intensity=int(d.get("intensity", 1)),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class Resolution:
    """One thing the resolver decided. The public record of a turn.

    `kind` is a stable machine-readable tag (`fuel_exhausted`,
    `action_rejected`, `air_defence_suppressed`, …) so the UI and the tests can
    key on it. `reason` is for a human, and for the narrator to read.
    """

    kind: str
    actor: str | None = None
    region: str | None = None
    reason: str = ""
    detail: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "actor": self.actor,
            "region": self.region,
            "reason": self.reason,
            "detail": self.detail,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Resolution:
        return cls(
            kind=d["kind"],
            actor=d.get("actor"),
            region=d.get("region"),
            reason=d.get("reason", ""),
            detail=dict(d.get("detail") or {}),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class ActorState:
    id: str
    name: str
    fuel_days: float
    munitions: float
    political_capital: float
    domestic_support: float
    intl_legitimacy: float
    isr: float
    escalation_rung: int = 0

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> ActorState:
        return cls(**d)


@dataclasses.dataclass(frozen=True, slots=True)
class RegionState:
    id: str
    name: str
    owner: str
    adjacency: tuple[str, ...]
    centroid: tuple[float, float]
    control: float
    infrastructure: float
    civilian_distress: float
    population: int
    terrain: str
    country: str = ""

    def to_json(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["adjacency"] = list(self.adjacency)
        d["centroid"] = list(self.centroid)
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> RegionState:
        d = dict(d)
        d["adjacency"] = tuple(d["adjacency"])
        lat, lon = d["centroid"]
        d["centroid"] = (float(lat), float(lon))
        d["population"] = int(d["population"])
        return cls(**d)


@dataclasses.dataclass(frozen=True, slots=True)
class Force:
    id: str
    owner: str
    kind: str
    strength: float
    readiness: float
    region: str
    posture: str

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Force:
        return cls(**d)


@dataclasses.dataclass(frozen=True, slots=True)
class WorldState:
    """A complete, self-contained snapshot. No hidden state lives anywhere else.

    `relations` is keyed `"FROM>TO"` rather than by a tuple, so the JSON form
    needs no key translation and the digest stays trivially stable.
    """

    turn: int
    actors: dict[str, ActorState]
    regions: dict[str, RegionState]
    forces: tuple[Force, ...]
    relations: dict[str, int] = dataclasses.field(default_factory=dict)
    log: tuple[Resolution, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "actors": {k: v.to_json() for k, v in self.actors.items()},
            "regions": {k: v.to_json() for k, v in self.regions.items()},
            "forces": [f.to_json() for f in self.forces],
            "relations": dict(self.relations),
            "log": [r.to_json() for r in self.log],
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> WorldState:
        return cls(
            turn=int(d["turn"]),
            actors={k: ActorState.from_json(v) for k, v in d["actors"].items()},
            regions={k: RegionState.from_json(v) for k, v in d["regions"].items()},
            forces=tuple(Force.from_json(f) for f in d["forces"]),
            relations=dict(d.get("relations") or {}),
            log=tuple(Resolution.from_json(r) for r in d.get("log") or ()),
        )

    def digest(self) -> str:
        """sha256 over the canonical JSON. Order-independent by construction."""
        canonical = json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    # --- convenience accessors, all read-only ---

    def forces_of(self, actor: str) -> tuple[Force, ...]:
        return tuple(f for f in self.forces if f.owner == actor)

    def forces_in(self, region: str) -> tuple[Force, ...]:
        return tuple(f for f in self.forces if f.region == region)

    def relation(self, a: str, b: str) -> int:
        return self.relations.get(f"{a}>{b}", 0)

    def regions_of(self, actor: str) -> tuple[RegionState, ...]:
        return tuple(r for r in self.regions.values() if r.owner == actor)

    def replace_forces(self, forces: tuple[Force, ...]) -> WorldState:
        return dataclasses.replace(self, forces=forces)


def sum_strength(forces: tuple[Force, ...], kind: str | None = None) -> float:
    return sum(f.strength for f in forces if kind is None or f.kind == kind)
