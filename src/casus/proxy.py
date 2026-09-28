"""The surface a scenario's rules see, and the ledger that records every change.

A rule reads the world through views (`s.actor(id)`, `s.places`, `s.find(...)`)
and changes it only through the mutation calls (`s.add`, `s.set`, `s.transfer`,
`s.decay`, `s.move`, `s.spawn`, `s.despawn`). Every mutation writes a ledger
entry naming the rule, the path, and the value before and after. That is what
turns "why did domestic support fall to zero" into a query.

Attribute access on a view yields a `Ref`: the current value, plus the path it
came from. A `Ref` behaves as its value in arithmetic, comparison and as a dict
key, and it is what the mutation calls take, so `s.add` knows what it changes.

The module performs no I/O and makes no model call.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import math
import random
from collections.abc import Iterator
from typing import Any

from .state import Actor, Entity, Event, Place, WorldState

UNBOUNDED = (-math.inf, math.inf)


class RuleError(RuntimeError):
    """A rule used the surface in a way the engine does not allow."""


class ReadOnly(RuleError):
    """A mutation was attempted where the world must not change."""


class UnknownName(KeyError):
    """A rule named an actor, place, entity, resource or attribute that does not exist."""

    def __init__(self, kind: str, name: str, where: str = ""):
        self.kind = kind
        self.name = name
        self.message = f"unknown {kind} '{name}'" + (f" on {where}" if where else "")
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


@dataclasses.dataclass(frozen=True, slots=True)
class Mutation:
    rule: str
    ref: str
    before: Any
    after: Any
    turn: int
    phase: str

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _unwrap(value: Any) -> Any:
    return value.value if isinstance(value, Ref) else value


class Ref:
    """A value that remembers where it came from."""

    __slots__ = ("path", "value")

    def __init__(self, path: str, value: Any):
        self.path = path
        self.value = value

    def __repr__(self) -> str:
        return f"Ref({self.path!r}, {self.value!r})"

    def __str__(self) -> str:
        return str(self.value)

    def __format__(self, spec: str) -> str:
        return format(self.value, spec)

    def __hash__(self) -> int:
        return hash(self.value)

    def __bool__(self) -> bool:
        return bool(self.value)

    def __float__(self) -> float:
        return float(self.value)

    def __int__(self) -> int:
        return int(self.value)

    def __round__(self, ndigits=None):
        return round(self.value, ndigits)

    def __abs__(self):
        return abs(self.value)

    def __neg__(self):
        return -self.value

    def __pos__(self):
        return +self.value

    def __eq__(self, other):
        return self.value == _unwrap(other)

    def __ne__(self, other):
        return self.value != _unwrap(other)

    def __lt__(self, other):
        return self.value < _unwrap(other)

    def __le__(self, other):
        return self.value <= _unwrap(other)

    def __gt__(self, other):
        return self.value > _unwrap(other)

    def __ge__(self, other):
        return self.value >= _unwrap(other)

    def __add__(self, other):
        return self.value + _unwrap(other)

    def __radd__(self, other):
        return _unwrap(other) + self.value

    def __sub__(self, other):
        return self.value - _unwrap(other)

    def __rsub__(self, other):
        return _unwrap(other) - self.value

    def __mul__(self, other):
        return self.value * _unwrap(other)

    def __rmul__(self, other):
        return _unwrap(other) * self.value

    def __truediv__(self, other):
        return self.value / _unwrap(other)

    def __rtruediv__(self, other):
        return _unwrap(other) / self.value

    def __floordiv__(self, other):
        return self.value // _unwrap(other)

    def __rfloordiv__(self, other):
        return _unwrap(other) // self.value

    def __mod__(self, other):
        return self.value % _unwrap(other)

    def __rmod__(self, other):
        return _unwrap(other) % self.value

    def __pow__(self, other):
        return self.value ** _unwrap(other)

    def __rpow__(self, other):
        return _unwrap(other) ** self.value


# --- views ------------------------------------------------------------------


class _View:
    """Live access to one record. Fixed fields read directly; anything else is a
    named quantity and comes back as a `Ref`."""

    _scope = ""
    _fixed: tuple[str, ...] = ()

    def __init__(self, state: State, ident: str):
        object.__setattr__(self, "_state", state)
        object.__setattr__(self, "id", ident)

    def _record(self) -> dict[str, Any]:
        raise NotImplementedError

    def _quantities(self) -> dict[str, Any]:
        raise NotImplementedError

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        record = self._record()
        if name in self._fixed:
            return record[name]
        quantities = self._quantities()
        if name not in quantities:
            raise UnknownName(self._noun, name, where=f"{self._scope} '{self.id}'")
        return Ref(f"{self._scope}.{self.id}.{name}", quantities[name])

    def __setattr__(self, name: str, value: Any) -> None:
        raise RuleError(
            f"assigning {self._scope}.{self.id}.{name} directly bypasses the ledger; "
            f"use s.set(...) or s.add(...)"
        )

    def __eq__(self, other) -> bool:
        return type(other) is type(self) and other.id == self.id

    def __hash__(self) -> int:
        return hash((self._scope, self.id))

    def __repr__(self) -> str:
        return f"<{self._scope} {self.id}>"


class ActorView(_View):
    _scope = "actor"
    _noun = "resource"
    _fixed = ("name",)

    def _record(self):
        return self._state._actors[self.id]

    def _quantities(self):
        return self._record()["resources"]


class PlaceView(_View):
    _scope = "place"
    _noun = "attribute"
    _fixed = ("name", "owner", "adjacency")

    def _record(self):
        return self._state._places[self.id]

    def _quantities(self):
        return self._record()["attrs"]


class EntityView(_View):
    _scope = "entity"
    _noun = "attribute"
    _fixed = ("owner", "kind", "place")

    def _record(self):
        return self._state._entity_record(self.id)

    def _quantities(self):
        return self._record()["attrs"]


@dataclasses.dataclass(frozen=True, slots=True)
class ActionView:
    """One action as a rule sees it: the declaration plus the scenario's
    read-only description of that action type."""

    actor: str
    type: str
    place: str | None
    target: str | None
    entities: tuple[str, ...]
    intensity: int
    declared: dict[str, Any]

    @classmethod
    def of(cls, action, declarations: dict[str, dict[str, Any]]) -> ActionView:
        return cls(
            actor=action.actor,
            type=action.type,
            place=action.place,
            target=action.target,
            entities=tuple(action.entities),
            intensity=action.intensity,
            declared=dict(declarations.get(action.type, {})),
        )

    def key(self) -> tuple:
        return (self.actor, self.type, self.place or "", self.target or "", self.entities)


# --- the state --------------------------------------------------------------


class State:
    """A mutable working copy of a `WorldState`, reachable only through views and
    the mutation calls."""

    def __init__(
        self,
        world: WorldState,
        rng: random.Random,
        resource_bounds: dict[str, tuple[float, float]] | None = None,
        attribute_bounds: dict[str, tuple[float, float]] | None = None,
    ):
        self.turn = world.turn
        self._rng = rng
        self._resource_bounds = dict(resource_bounds or {})
        self._attribute_bounds = dict(attribute_bounds or {})
        self._actors = {
            k: {"name": a.name, "resources": dict(a.resources)} for k, a in world.actors.items()
        }
        self._places = {
            k: {
                "name": p.name,
                "owner": p.owner,
                "adjacency": tuple(p.adjacency),
                "attrs": dict(p.attrs),
            }
            for k, p in world.places.items()
        }
        self._entities = [
            {
                "id": e.id,
                "owner": e.owner,
                "kind": e.kind,
                "place": e.place,
                "attrs": dict(e.attrs),
            }
            for e in world.entities
        ]
        self._events: list[Event] = []
        self._ledger: list[Mutation] = []
        self._actions: list[ActionView] = []
        self._rejected: dict[tuple, str] = {}
        self._rule = ""
        self._phase = ""
        self._action: ActionView | None = None
        self._visible = 0
        self._read_only = ""

    # --- context --------------------------------------------------------

    @contextlib.contextmanager
    def attributing(
        self, rule: str, phase: str, action: ActionView | None = None
    ) -> Iterator[None]:
        """Run one rule invocation: mutations are attributed to it, and it sees
        only events emitted before it started."""
        saved = (self._rule, self._phase, self._action, self._visible)
        self._rule, self._phase, self._action = rule, phase, action
        self._visible = len(self._events)
        try:
            yield
        finally:
            self._rule, self._phase, self._action, self._visible = saved

    def read_only(self, purpose: str) -> State:
        """The same world, with every mutation call refused."""
        view = copy.copy(self)
        view._read_only = purpose
        return view

    def scratch(self) -> State:
        """An independent copy. Its mutations never reach this state, and its
        ledger is its own."""
        other = copy.copy(self)
        other._actors = copy.deepcopy(self._actors)
        other._places = copy.deepcopy(self._places)
        other._entities = copy.deepcopy(self._entities)
        other._events = list(self._events)
        other._ledger = []
        other._read_only = ""
        return other

    def set_actions(self, actions: list[ActionView]) -> None:
        self._actions = list(actions)

    def rejected(self, action: ActionView) -> str | None:
        return self._rejected.get(action.key())

    @property
    def ledger(self) -> list[Mutation]:
        return list(self._ledger)

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    def freeze(self) -> WorldState:
        return WorldState(
            turn=self.turn,
            actors={
                k: Actor(id=k, name=v["name"], resources=dict(v["resources"]))
                for k, v in self._actors.items()
            },
            places={
                k: Place(
                    id=k,
                    name=v["name"],
                    owner=v["owner"],
                    adjacency=tuple(v["adjacency"]),
                    attrs=dict(v["attrs"]),
                )
                for k, v in self._places.items()
            },
            entities=tuple(
                Entity(
                    id=e["id"],
                    owner=e["owner"],
                    kind=e["kind"],
                    place=e["place"],
                    attrs=dict(e["attrs"]),
                )
                for e in self._entities
            ),
            events=tuple(self._events),
        )

    # --- reading --------------------------------------------------------

    @property
    def rng(self) -> random.Random:
        """The one seeded generator. The only randomness a rule may use."""
        return self._rng

    def actor(self, ident: str) -> ActorView:
        if ident not in self._actors:
            raise UnknownName("actor", ident)
        return ActorView(self, ident)

    def place(self, ident: str) -> PlaceView:
        if ident not in self._places:
            raise UnknownName("place", ident)
        return PlaceView(self, ident)

    def entity(self, ident: str) -> EntityView:
        self._entity_record(ident)
        return EntityView(self, ident)

    @property
    def actors(self) -> list[ActorView]:
        return [ActorView(self, k) for k in self._actors]

    @property
    def places(self) -> list[PlaceView]:
        return [PlaceView(self, k) for k in self._places]

    @property
    def entities(self) -> list[EntityView]:
        return [EntityView(self, e["id"]) for e in self._entities]

    def find(
        self, kind: str | None = None, owner: str | None = None, place: str | None = None
    ) -> list[EntityView]:
        return [
            EntityView(self, e["id"])
            for e in self._entities
            if (kind is None or e["kind"] == _unwrap(kind))
            and (owner is None or e["owner"] == _unwrap(owner))
            and (place is None or e["place"] == _unwrap(place))
        ]

    @property
    def actions(self) -> list[ActionView]:
        if self._phase == "legality":
            return list(self._actions)
        return [a for a in self._actions if a.key() not in self._rejected]

    # --- mutation -------------------------------------------------------

    def add(self, ref: Ref, delta: float) -> None:
        self._check_writable("add")
        current = self._read(ref)
        self._write(ref, self._clamp(ref.path, current + _unwrap(delta)))

    def set(self, ref: Ref, value: Any) -> None:
        self._check_writable("set")
        value = _unwrap(value)
        if not isinstance(value, str):
            value = self._clamp(ref.path, value)
        self._write(ref, value)

    def transfer(self, source: Ref, target: Ref, amount: float) -> None:
        """Move `amount` from one quantity to another. Moves only what both
        bounds allow, so the total is conserved."""
        self._check_writable("transfer")
        amount = _unwrap(amount)
        have = self._read(source)
        room = self._read(target)
        src_lo, _ = self._bounds(source.path)
        _, dst_hi = self._bounds(target.path)
        moved = min(amount, have - src_lo, dst_hi - room)
        if moved <= 0:
            return
        self._write(source, have - moved)
        self._write(target, room + moved)

    def decay(self, ref: Ref, toward: float, rate: float) -> None:
        """Move a fraction `rate` of the way to `toward`. Never past it."""
        self._check_writable("decay")
        current = self._read(ref)
        rate = max(0.0, min(1.0, _unwrap(rate)))
        self._write(ref, self._clamp(ref.path, current + (_unwrap(toward) - current) * rate))

    def move(self, entity: EntityView | str, place: str) -> None:
        self._check_writable("move")
        ident = entity.id if isinstance(entity, EntityView) else entity
        place = _unwrap(place)
        if place not in self._places:
            raise UnknownName("place", place)
        record = self._entity_record(ident)
        before = record["place"]
        if before == place:
            return
        record["place"] = place
        self._record(f"entity.{ident}.place", before, place)

    def spawn(self, *, id: str, kind: str, owner: str, place: str, **attrs: Any) -> EntityView:
        self._check_writable("spawn")
        if any(e["id"] == id for e in self._entities):
            raise ValueError(f"entity '{id}' already exists")
        if place not in self._places:
            raise UnknownName("place", place)
        record = {
            "id": id,
            "owner": _unwrap(owner),
            "kind": _unwrap(kind),
            "place": _unwrap(place),
            "attrs": {k: _unwrap(v) for k, v in attrs.items()},
        }
        self._entities.append(record)
        self._record(f"entity.{id}", None, copy.deepcopy(record))
        return EntityView(self, id)

    def despawn(self, entity: EntityView | str) -> None:
        self._check_writable("despawn")
        ident = entity.id if isinstance(entity, EntityView) else entity
        record = self._entity_record(ident)
        self._entities.remove(record)
        self._record(f"entity.{ident}", copy.deepcopy(record), None)

    # --- events ---------------------------------------------------------

    def emit(self, ident: str, **detail: Any) -> None:
        self._check_writable("emit")
        self._events.append(Event(id=ident, detail={k: _unwrap(v) for k, v in detail.items()}))

    def happened(self, ident: str, **match: Any) -> bool:
        """Whether an earlier phase or an earlier rule emitted a matching event."""
        wanted = {k: _unwrap(v) for k, v in match.items()}
        return any(
            e.id == ident and all(e.detail.get(k) == v for k, v in wanted.items())
            for e in self._events[: self._visible]
        )

    def reject(self, reason: str) -> None:
        if self._phase != "legality":
            raise RuleError(
                f"reject() is only callable in the legality phase, not {self._phase!r}"
            )
        if self._action is None:
            raise RuleError("reject() needs a rule declared with on=<action type>")
        key = self._action.key()
        if key in self._rejected:
            return
        self._rejected[key] = reason
        action = self._action
        self._events.append(
            Event(
                id="action_rejected",
                detail={
                    "actor": action.actor,
                    "place": action.place,
                    "reason": reason,
                    "action": {
                        "actor": action.actor,
                        "type": action.type,
                        "place": action.place,
                        "target": action.target,
                        "entities": list(action.entities),
                        "intensity": action.intensity,
                    },
                },
            )
        )

    # --- internals ------------------------------------------------------

    def _entity_record(self, ident: str) -> dict[str, Any]:
        for record in self._entities:
            if record["id"] == ident:
                return record
        raise UnknownName("entity", ident)

    def _check_writable(self, call: str) -> None:
        if self._read_only:
            raise ReadOnly(f"{self._read_only} may not change the world (called s.{call})")

    def _locate(self, path: str) -> tuple[dict[str, Any], str]:
        scope, ident, name = path.split(".", 2)
        if scope == "actor":
            return self._actors[ident]["resources"], name
        if scope == "place":
            return self._places[ident]["attrs"], name
        if scope == "entity":
            return self._entity_record(ident)["attrs"], name
        raise RuleError(f"cannot mutate '{path}'")

    def _read(self, ref: Ref) -> Any:
        if not isinstance(ref, Ref):
            raise RuleError(
                f"mutation calls take a reference such as s.place('x').infra, not {ref!r}"
            )
        store, name = self._locate(ref.path)
        return store[name]

    def _write(self, ref: Ref, value: Any) -> None:
        store, name = self._locate(ref.path)
        before = store[name]
        if before == value:
            return
        store[name] = value
        self._record(ref.path, before, value)

    def _record(self, path: str, before: Any, after: Any) -> None:
        self._ledger.append(
            Mutation(
                rule=self._rule,
                ref=path,
                before=before,
                after=after,
                turn=self.turn,
                phase=self._phase,
            )
        )

    def _bounds(self, path: str) -> tuple[float, float]:
        scope, _, name = path.split(".", 2)
        table = self._resource_bounds if scope == "actor" else self._attribute_bounds
        return table.get(name, UNBOUNDED)

    def _clamp(self, path: str, value: float) -> float:
        lo, hi = self._bounds(path)
        return max(lo, min(hi, value))
