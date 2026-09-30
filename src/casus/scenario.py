"""A scenario is a directory: `scenario.yaml` for the data, `rules.py` for the physics.

The YAML names the actors, their briefings and models, the resources they hold,
the places and entities, the actions a player may declare, and how the rest of
the engine should display all of it. The Python holds the rules. A scenario may
instead name a ruleset the repo ships (`rules: reference`).

Structural mistakes (an unknown owner, an undeclared resource, an action field
outside the vocabulary) fail at the door, because a typo should not surface as a
rejected action on turn four.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import types
from typing import Any

import yaml

from .geo.digest import region_digest
from .ruleset import RuleSet
from .state import Actor, Entity, Place, WorldState
from .validate import Finding
from .validate.static import check_source

#: The fields an action may carry. Each maps to one field of `state.Action`.
ACTION_FIELDS = frozenset({"place", "target", "entities", "intensity"})

#: Where shipped rulesets live, for `rules: <name>`.
SHIPPED = pathlib.Path(__file__).resolve().parents[2] / "scenarios"

#: Where `casus regions` writes a scenario's polygons and computed adjacency.
REGIONS_FILE = "regions.json"


class ScenarioError(ValueError):
    """The scenario does not describe a usable world."""


class ScenarioInvalid(ScenarioError):
    """The validator found problems. Carries every finding, not just the first."""

    def __init__(self, findings):
        self.findings = list(findings)
        super().__init__(
            f"{len(self.findings)} finding(s):\n" + "\n".join(f"  {f}" for f in self.findings)
        )


def _bounds(declarations: dict[str, dict[str, Any]]) -> dict[str, tuple[float, float]]:
    return {
        name: (float(spec.get("min", float("-inf"))), float(spec.get("max", float("inf"))))
        for name, spec in declarations.items()
    }


def _number_or_text(value: Any) -> float | str:
    return value if isinstance(value, str) else float(value)


@dataclasses.dataclass(frozen=True)
class Scenario:
    data: dict[str, Any]
    rules_source: str
    ruleset: RuleSet
    origin: str = ""
    #: The module the rules were executed into, for reading a ruleset's constants.
    module: types.ModuleType | None = dataclasses.field(default=None, compare=False, repr=False)
    #: regions.json as loaded, when the scenario has region blocks. The transcript
    #: carries it, so replay and the viewer need nothing else.
    regions: dict[str, Any] | None = dataclasses.field(default=None, compare=False, repr=False)
    #: Findings that do not stop a load: a plain adjacency list the regions disagree with.
    warnings: tuple[Finding, ...] = dataclasses.field(default=(), compare=False, repr=False)

    # --- loading --------------------------------------------------------

    @classmethod
    def load(cls, directory: str | pathlib.Path, validate: bool = True) -> Scenario:
        """Load a scenario directory. With `validate`, the dry turn runs as well as
        the static check, and any finding raises `ScenarioInvalid`."""
        directory = pathlib.Path(directory)
        manifest = directory / "scenario.yaml"
        if not manifest.is_file():
            raise ScenarioError(f"{directory} has no scenario.yaml")
        data = yaml.safe_load(manifest.read_text())
        if not isinstance(data, dict):
            raise ScenarioError("scenario.yaml must contain a mapping")
        regions, warnings = _apply_regions(directory, data)
        rules_path = cls._rules_path(directory, data.get("rules"))
        scenario = cls.from_parts(data, rules_path.read_text(), origin=str(rules_path))
        scenario = dataclasses.replace(scenario, regions=regions, warnings=tuple(warnings))
        if validate:
            from .validate.dynamic import dry_run

            findings = dry_run(scenario).findings
            if findings:
                raise ScenarioInvalid(findings)
        return scenario

    @staticmethod
    def _rules_path(directory: pathlib.Path, named: str | None) -> pathlib.Path:
        if not named:
            path = directory / "rules.py"
            if not path.is_file():
                raise ScenarioError(f"{directory} has no rules.py and names no ruleset")
            return path
        for root in (directory.parent, SHIPPED):
            path = root / str(named) / "rules.py"
            if path.is_file():
                return path
        raise ScenarioError(f"no shipped ruleset named '{named}'")

    @classmethod
    def from_parts(cls, data: dict[str, Any], rules_source: str, origin: str = "") -> Scenario:
        """Build a scenario from its data and its rules source. The static check
        always runs, because the source is about to be executed."""
        _check_structure(data)
        findings = check_source(rules_source, origin or "<rules.py>")
        if findings:
            raise ScenarioInvalid(findings)
        module = load_rules(rules_source, origin or "<rules.py>")
        return cls(
            data=data,
            rules_source=rules_source,
            ruleset=RuleSet.from_module(module),
            origin=origin,
            module=module,
        )

    # --- what the engine reads -----------------------------------------

    @property
    def name(self) -> str:
        return str(self.data["name"])

    @property
    def turns(self) -> int:
        return int(self.data.get("turns", 6))

    @property
    def actors(self) -> tuple[str, ...]:
        return tuple(self.data["actors"])

    @property
    def actions(self) -> dict[str, dict[str, Any]]:
        return dict(self.data.get("actions") or {})

    @property
    def resources(self) -> dict[str, dict[str, Any]]:
        return dict(self.data.get("resources") or {})

    @property
    def attributes(self) -> dict[str, dict[str, Any]]:
        return dict(self.data.get("attributes") or {})

    @property
    def display(self) -> dict[str, Any]:
        return dict(self.data.get("display") or {})

    def resource_bounds(self) -> dict[str, tuple[float, float]]:
        return _bounds(self.resources)

    def attribute_bounds(self) -> dict[str, tuple[float, float]]:
        return _bounds(self.attributes)

    def language(self) -> str:
        return str(self.data.get("language", "en") or "en")

    def briefing(self, actor: str) -> str:
        return str(self.data["actors"][actor]["briefing"])

    def model(self, actor: str) -> str:
        return str(self.data["actors"][actor]["model"])

    def narrator_model(self) -> str:
        return str(self.data.get("narrator_model", "") or "")

    def initial_state(self) -> WorldState:
        d = self.data
        return WorldState(
            turn=1,
            actors={
                a: Actor(
                    id=a,
                    name=str(spec.get("name", a)),
                    resources={k: float(v) for k, v in (spec.get("resources") or {}).items()},
                )
                for a, spec in d["actors"].items()
            },
            places={
                p: Place(
                    id=p,
                    name=str(spec.get("name", p)),
                    owner=str(spec.get("owner") or ""),
                    adjacency=tuple(spec.get("adjacency") or ()),
                    attrs={k: _number_or_text(v) for k, v in (spec.get("attrs") or {}).items()},
                )
                for p, spec in d["places"].items()
            },
            entities=tuple(
                Entity(
                    id=str(e["id"]),
                    owner=str(e["owner"]),
                    kind=str(e["kind"]),
                    place=str(e["place"]),
                    attrs={k: _number_or_text(v) for k, v in (e.get("attrs") or {}).items()},
                )
                for e in d.get("entities") or ()
            ),
        )


def load_rules(source: str, origin: str) -> types.ModuleType:
    """Execute a scenario's rules into a fresh module. The static check has
    already run; here a failure is reported, not hidden."""
    module = types.ModuleType("casus_scenario_rules")
    module.__file__ = origin
    try:
        # Executing the scenario's own code is the point; the static check runs first.
        exec(compile(source, origin, "exec"), module.__dict__)  # noqa: S102
    except Exception as exc:
        raise ScenarioError(f"{origin} failed to load: {type(exc).__name__}: {exc}") from exc
    return module


def _apply_regions(directory: pathlib.Path, data: dict[str, Any]) -> tuple[dict | None, list]:
    """Fill each place's adjacency from regions.json: the computed graph, then the
    YAML's `add`/`remove` exceptions, applied at both ends so no edge is one-way.
    A plain list stays authoritative for its place; where it disagrees with the
    regions that is a warning, so an older scenario migrates one place at a time.
    Needs neither shapely nor the map data: `casus regions` did the geometry."""
    places = data.get("places")
    if not isinstance(places, dict) or not any(
        isinstance(spec, dict) and "region" in spec for spec in places.values()
    ):
        return None, []
    path = directory / REGIONS_FILE
    fix = f"run: casus regions {directory}"
    if not path.is_file():
        raise ScenarioError(f"{directory} has region blocks but no {REGIONS_FILE}; {fix}")
    regions = json.loads(path.read_text(encoding="utf-8"))
    theatre = (data.get("display") or {}).get("theatre")
    if regions.get("digest") != region_digest(places, theatre):
        raise ScenarioError(
            f"{path} is stale: the region blocks changed since it was computed; {fix}"
        )
    computed = regions.get("adjacency") or {}
    graph = {
        place_id: set(computed.get(place_id, ()))
        for place_id, spec in places.items()
        if isinstance(spec, dict) and "region" in spec
    }
    for place_id, spec in places.items():
        exceptions = (spec or {}).get("adjacency")
        if not isinstance(exceptions, dict):
            continue
        if place_id not in graph:
            raise ScenarioError(
                f"place '{place_id}' lists adjacency exceptions but has no region block"
            )
        verbs = set(exceptions) - {"add", "remove"}
        if verbs:
            raise ScenarioError(
                f"place '{place_id}': adjacency exceptions are add and remove, "
                f"not {sorted(verbs)}"
            )
        for verb in ("add", "remove"):
            for other in exceptions.get(verb) or ():
                if other not in places:
                    raise ScenarioError(
                        f"place '{place_id}' {verb}s adjacency to unknown place '{other}'"
                    )
                if verb == "add":
                    graph[place_id].add(other)
                    graph.setdefault(other, set()).add(place_id)
                else:
                    graph[place_id].discard(other)
                    graph.get(other, set()).discard(place_id)
    warnings = []
    for place_id, spec in places.items():
        listed = (spec or {}).get("adjacency")
        if isinstance(listed, list):
            if place_id in graph and set(listed) != graph[place_id]:
                warnings.append(
                    Finding(
                        "adjacency-differs",
                        f"place '{place_id}' lists {sorted(listed)}; its region gives "
                        f"{sorted(graph[place_id])}",
                        str(path),
                    )
                )
        elif place_id in graph:
            spec["adjacency"] = sorted(graph[place_id])
    return regions, warnings


def _check_structure(d: dict[str, Any]) -> None:
    for key in ("name", "actors", "places", "actions"):
        if key not in d:
            raise ScenarioError(f"scenario is missing '{key}'")

    actors, places = d["actors"], d["places"]
    resources = set((d.get("resources") or {}).keys())

    for action, spec in d["actions"].items():
        unknown = set((spec or {}).get("fields") or ()) - ACTION_FIELDS
        if unknown:
            raise ScenarioError(
                f"action '{action}' uses unknown field(s) {sorted(unknown)}; "
                f"the fields are {sorted(ACTION_FIELDS)}"
            )

    for actor_id, spec in actors.items():
        for field in ("briefing", "model"):
            if not spec.get(field):
                raise ScenarioError(f"actor '{actor_id}' has no {field}")
        for resource in spec.get("resources") or {}:
            if resource not in resources:
                raise ScenarioError(
                    f"actor '{actor_id}' holds '{resource}', which is not declared under resources"
                )

    for place_id, spec in places.items():
        owner = spec.get("owner") or ""
        if owner and owner not in actors:
            raise ScenarioError(f"place '{place_id}' is owned by unknown actor '{owner}'")
        adjacency = spec.get("adjacency") or ()
        if isinstance(adjacency, dict):
            raise ScenarioError(
                f"place '{place_id}' lists adjacency exceptions "
                f"({', '.join(sorted(adjacency))}); only Scenario.load applies them, "
                "from regions.json"
            )
        for neighbour in adjacency:
            if neighbour not in places:
                raise ScenarioError(
                    f"place '{place_id}' is adjacent to unknown place '{neighbour}'"
                )

    seen: set[str] = set()
    for entity in d.get("entities") or ():
        ident = entity.get("id", "<unnamed>")
        if ident in seen:
            raise ScenarioError(f"duplicate entity id '{ident}'")
        seen.add(ident)
        if entity.get("owner") not in actors:
            raise ScenarioError(f"entity '{ident}' has unknown owner '{entity.get('owner')}'")
        if entity.get("place") not in places:
            raise ScenarioError(f"entity '{ident}' is in unknown place '{entity.get('place')}'")
