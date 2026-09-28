"""The world as data, with no meaning attached.

Actors hold named resources, places hold named attributes, entities have an
owner, a kind and a place, and events describe what happened this turn. None of
the names mean anything to the engine: a scenario declares them and its rules
interpret them.

A canonical JSON form and a digest over it make replay verification meaningful.
The digest is independent of key order, so a mismatch means a value changed, not
that a dict was built in another order. Entity order is part of the state,
because it decides which entity a rule finds first.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any

Value = float | str


@dataclasses.dataclass(frozen=True, slots=True)
class Actor:
    id: str
    name: str
    resources: dict[str, float]

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "resources": dict(self.resources)}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Actor:
        return cls(id=d["id"], name=d["name"], resources=dict(d["resources"]))


@dataclasses.dataclass(frozen=True, slots=True)
class Place:
    id: str
    name: str
    owner: str
    adjacency: tuple[str, ...]
    attrs: dict[str, Value]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "owner": self.owner,
            "adjacency": list(self.adjacency),
            "attrs": dict(self.attrs),
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Place:
        return cls(
            id=d["id"],
            name=d["name"],
            owner=d["owner"],
            adjacency=tuple(d["adjacency"]),
            attrs=dict(d["attrs"]),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class Entity:
    id: str
    owner: str
    kind: str
    place: str
    attrs: dict[str, Value]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "owner": self.owner,
            "kind": self.kind,
            "place": self.place,
            "attrs": dict(self.attrs),
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Entity:
        return cls(
            id=d["id"], owner=d["owner"], kind=d["kind"], place=d["place"], attrs=dict(d["attrs"])
        )


@dataclasses.dataclass(frozen=True, slots=True)
class Event:
    """Something that happened this turn. `detail` conventionally carries
    `actor`, `place` and `reason`, which the narrator and the viewer read."""

    id: str
    detail: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "detail": dict(self.detail)}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Event:
        return cls(id=d["id"], detail=dict(d.get("detail") or {}))


@dataclasses.dataclass(frozen=True, slots=True)
class Action:
    """One declared intent. Emitted by a player, never by a rule."""

    actor: str
    type: str
    place: str | None = None
    target: str | None = None
    entities: tuple[str, ...] = ()
    intensity: int = 1

    def to_json(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "type": self.type,
            "place": self.place,
            "target": self.target,
            "entities": list(self.entities),
            "intensity": self.intensity,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Action:
        return cls(
            actor=d["actor"],
            type=d["type"],
            place=d.get("place"),
            target=d.get("target"),
            entities=tuple(d.get("entities") or ()),
            intensity=int(d.get("intensity", 1)),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class WorldState:
    """A complete, self-contained snapshot. No hidden state lives anywhere else.

    `events` holds what happened in the turn that produced this state.
    """

    turn: int
    actors: dict[str, Actor]
    places: dict[str, Place]
    entities: tuple[Entity, ...]
    events: tuple[Event, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "actors": {k: v.to_json() for k, v in self.actors.items()},
            "places": {k: v.to_json() for k, v in self.places.items()},
            "entities": [e.to_json() for e in self.entities],
            "events": [e.to_json() for e in self.events],
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> WorldState:
        return cls(
            turn=int(d["turn"]),
            actors={k: Actor.from_json(v) for k, v in d["actors"].items()},
            places={k: Place.from_json(v) for k, v in d["places"].items()},
            entities=tuple(Entity.from_json(e) for e in d["entities"]),
            events=tuple(Event.from_json(e) for e in d.get("events") or ()),
        )

    def digest(self) -> str:
        """sha256 over the canonical JSON. Order-independent for keys."""
        canonical = json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
