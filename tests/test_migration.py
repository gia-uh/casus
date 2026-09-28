"""The spec's acceptance criterion: the ported Caribbean reproduces the trajectory
v1 recorded.

Digests cannot match across a change of state shape, so both states are
projected onto the same flat paths (`actor.US.fuel_days`, `place.x.control`,
`entity.f.strength`) and compared value by value. Every v1 field is either
mapped or named as deliberately dropped; a field that is neither fails the test
by name, so nothing drops out of the comparison unnoticed.
"""

from __future__ import annotations

import collections
import os
import pathlib

import pytest

from casus import engine
from casus.scenario import Scenario
from casus.state import Action, WorldState

ROOT = pathlib.Path(__file__).parent.parent
REFERENCE_RUN = pathlib.Path(
    os.environ.get("CASUS_REFERENCE_RUN", ROOT / "runs" / "caribbean-lingo-101.jsonl")
)
CARIBBEAN = ROOT / "scenarios" / "private" / "caribbean-2026"

requires_reference = pytest.mark.skipif(
    not (REFERENCE_RUN.is_file() and (CARIBBEAN / "scenario.yaml").is_file()),
    reason=(
        "needs runs/caribbean-lingo-101.jsonl and scenarios/private, which git does "
        "not carry; run on zion, with CASUS_REFERENCE_RUN set when in a worktree"
    ),
)

ACTOR_RESOURCES = (
    "fuel_days", "fuel_inflow", "munitions", "political_capital", "domestic_support",
    "intl_legitimacy", "isr", "reserve_pool", "escalation_rung",
)  # fmt: skip
PLACE_ATTRS = ("control", "infrastructure", "civilian_distress", "population", "terrain", "country")
FORCE_ATTRS = ("strength", "readiness", "posture")

#: v1 fields v2 drops on purpose. `relations` was carried in the state and the
#: digest and read by no rule; `log` is compared separately, as events.
DROPPED = {"state": {"relations", "log"}}
KNOWN = {
    "state": {"turn", "actors", "regions", "forces"},
    "actor": {"id", "name", *ACTOR_RESOURCES},
    "region": {"id", "name", "owner", "adjacency", "centroid", *PLACE_ATTRS},
    "force": {"id", "owner", "kind", "region", *FORCE_ATTRS},
}


def _unmapped(scope: str, record: dict) -> set[str]:
    return set(record) - KNOWN[scope] - DROPPED.get(scope, set())


def project_v1(state: dict) -> dict[str, object]:
    unmapped = {f"state.{k}" for k in _unmapped("state", state)}
    out: dict[str, object] = {"turn": state["turn"]}
    for a, actor in state["actors"].items():
        unmapped |= {f"actors.{a}.{k}" for k in _unmapped("actor", actor)}
        out[f"actor.{a}.name"] = actor["name"]
        for k in ACTOR_RESOURCES:
            out[f"actor.{a}.{k}"] = actor[k]
    for r, region in state["regions"].items():
        unmapped |= {f"regions.{r}.{k}" for k in _unmapped("region", region)}
        out[f"place.{r}.name"] = region["name"]
        out[f"place.{r}.owner"] = region["owner"]
        out[f"place.{r}.adjacency"] = list(region["adjacency"])
        out[f"place.{r}.lat"], out[f"place.{r}.lon"] = region["centroid"]
        for k in PLACE_ATTRS:
            out[f"place.{r}.{k}"] = region[k]
    for force in state["forces"]:
        unmapped |= {f"forces.{force['id']}.{k}" for k in _unmapped("force", force)}
        f = force["id"]
        out[f"entity.{f}.owner"] = force["owner"]
        out[f"entity.{f}.kind"] = force["kind"]
        out[f"entity.{f}.place"] = force["region"]
        for k in FORCE_ATTRS:
            out[f"entity.{f}.{k}"] = force[k]
    assert not unmapped, f"v1 fields with no v2 counterpart: {sorted(unmapped)}"
    return out


def project_v2(world: WorldState) -> dict[str, object]:
    out: dict[str, object] = {"turn": world.turn}
    for a, actor in world.actors.items():
        out[f"actor.{a}.name"] = actor.name
        for k, v in actor.resources.items():
            out[f"actor.{a}.{k}"] = v
    for p, place in world.places.items():
        out[f"place.{p}.name"] = place.name
        out[f"place.{p}.owner"] = place.owner
        out[f"place.{p}.adjacency"] = list(place.adjacency)
        for k, v in place.attrs.items():
            out[f"place.{p}.{k}"] = v
    for e in world.entities:
        out[f"entity.{e.id}.owner"] = e.owner
        out[f"entity.{e.id}.kind"] = e.kind
        out[f"entity.{e.id}.place"] = e.place
        for k, v in e.attrs.items():
            out[f"entity.{e.id}.{k}"] = v
    return out


def v1_action(record: dict) -> Action:
    """A recorded v1 action in v2's vocabulary."""
    return Action(
        actor=record["actor"],
        type=record["type"],
        place=record.get("region"),
        target=record.get("target_actor"),
        entities=tuple(record.get("forces") or ()),
        intensity=int(record.get("intensity", 1)),
    )


def first_divergence(recorded: list[dict], replayed: list[WorldState], tolerance=1e-9) -> str:
    """Name the first turn and path where the port leaves v1's trajectory."""
    for old, new in zip(recorded, replayed, strict=True):
        a, b = project_v1(old["state"]), project_v2(new)
        turn = old["turn"]
        if set(a) != set(b):
            return (
                f"turn {turn}: only in v1 {sorted(set(a) - set(b))}, "
                f"only in v2 {sorted(set(b) - set(a))}"
            )
        for path in sorted(a):
            x, y = a[path], b[path]
            numeric = isinstance(x, int | float) and isinstance(y, int | float)
            if (abs(x - y) > tolerance) if numeric else (x != y):
                return f"turn {turn}: {path} recorded {x!r}, port gives {y!r}"
        kinds = collections.Counter(r["kind"] for r in old["state"]["log"])
        ids = collections.Counter(e.id for e in new.events)
        if kinds != ids:
            return f"turn {turn}: v1 resolutions {dict(kinds)} but v2 events {dict(ids)}"
    return ""


@requires_reference
def test_the_ported_caribbean_reproduces_its_recorded_trajectory():
    """If it goes across whole, the rule surface is complete. If it does not, the
    first divergence names the turn and the quantity."""
    records = engine.read_records(REFERENCE_RUN)
    recorded = [r for r in records if r["kind"] == "state"]
    replayed = engine.replay_on(Scenario.load(CARIBBEAN), REFERENCE_RUN, translate=v1_action)
    assert len(recorded) == len(replayed.states) == 13
    assert first_divergence(recorded, replayed.states) == ""


def test_an_unmapped_v1_field_fails_by_name():
    state = {"turn": 1, "actors": {}, "regions": {}, "forces": [], "morale_index": 3}
    with pytest.raises(AssertionError, match="state.morale_index"):
        project_v1(state)
