#!/usr/bin/env python3
"""Convert a v1 scenario file into a v2 scenario directory that uses the shipped
`reference` ruleset.

A one-shot generator. Its output is committed; nothing imports this file. It
reads the v1 file through v1's own loader, so v1's defaults (60 fuel-days, 0.6
ISR, and the rest) carry over exactly rather than being restated here.

    uv run python tools/convert_v1_scenario.py scenarios/smoke.yaml scenarios/reference
    uv run python tools/convert_v1_scenario.py \\
        scenarios/private/caribbean-2026.yaml scenarios/private/caribbean-2026

The resource and attribute names are v1's field names unchanged, so a v1 state
and a v2 state can be compared field by field.
"""

from __future__ import annotations

import argparse
import math
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from casus.v1 import actions as v1_actions
from casus.v1 import rules as v1_rules
from casus.v1.scenario import Scenario as V1Scenario
from casus.v1.state import ESCALATION_RUNGS, RUNG_NAMES

RUNG_NAMES_ES = [
    "retórica",
    "económico",
    "demostración de fuerza",
    "interdicción",
    "encubierto / ciber",
    "ataques limitados",
    "campaña aérea",
    "invasión terrestre",
]

RESOURCES = {
    "fuel_days": {"min": 0},
    "fuel_inflow": {"min": 0},
    "munitions": {"min": 0, "max": 100},
    "political_capital": {"min": 0, "max": 100},
    "domestic_support": {"min": 0, "max": 100},
    "intl_legitimacy": {"min": 0, "max": 100},
    "isr": {"min": 0, "max": 1},
    "reserve_pool": {"min": 0},
    "escalation_rung": {"min": 0, "max": len(RUNG_NAMES) - 1},
}

ATTRIBUTES = {
    "control": {"min": 0, "max": 100},
    "infrastructure": {"min": 0, "max": 100},
    "civilian_distress": {"min": 0, "max": 100},
    "strength": {"min": 0},
}

DISPLAY = {
    "standing": ["fuel_days", "intl_legitimacy", "domestic_support"],
    "bands": {
        "fuel_days": {0.5: "exhausted", 15: "critical", 45: "strained", math.inf: "sufficient"},
        "isr": {0.25: "very poor", 0.5: "poor", 0.8: "adequate", math.inf: "excellent"},
        "intl_legitimacy": {40: "low", 70: "moderate", math.inf: "high"},
    },
    "labels": {
        "es": {
            "fuel_days": "combustible (días)",
            "fuel_inflow": "entrada de combustible",
            "munitions": "munición",
            "political_capital": "capital político",
            "domestic_support": "apoyo interno",
            "intl_legitimacy": "legitimidad internacional",
            "isr": "inteligencia",
            "reserve_pool": "reservas",
            "escalation_rung": "escalón",
            "control": "control",
            "infrastructure": "infraestructura",
            "civilian_distress": "sufrimiento civil",
            "population": "población",
            "terrain": "terreno",
        }
    },
    "ladder": {"resource": "escalation_rung", "en": list(RUNG_NAMES), "es": RUNG_NAMES_ES},
    "unreported": ["escalation"],
    "hidden": ["lat", "lon", "country"],
}


def actions() -> dict:
    out = {}
    for action_type in sorted(ESCALATION_RUNGS, key=lambda t: (ESCALATION_RUNGS[t], t)):
        uses = v1_actions.FIELDS[action_type]
        fields = []
        # v1 honoured a region only for these types and dropped it from the rest
        # (mobilize included, whatever its schema said), so the port declares a
        # place for exactly these.
        if action_type in v1_rules.REGIONAL_ACTIONS:
            fields.append("place")
        if "target" in uses:
            fields.append("target")
        if "forces" in uses:
            fields.append("entities")
        if "intensity" in uses:
            fields.append("intensity")
        out[action_type] = {
            "fields": fields,
            # v1 clamped every action's intensity, whatever its fields.
            "intensity": [v1_rules.INTENSITY_MIN, v1_rules.INTENSITY_MAX],
            "rung": ESCALATION_RUNGS[action_type],
            "description": v1_actions.DESCRIPTIONS[action_type],
        }
    return out


def convert(source: pathlib.Path) -> dict:
    v1 = V1Scenario.load(source)
    world = v1.initial_state()
    raw = v1.raw
    data: dict = {"name": raw["name"]}
    for key in ("language", "turns", "narrator_model", "description"):
        if key in raw:
            data[key] = raw[key]
    data["rules"] = "reference"
    data["resources"] = RESOURCES
    data["attributes"] = ATTRIBUTES
    data["actions"] = actions()
    data["actors"] = {
        a: {
            "name": state.name,
            "model": v1.model(a),
            "briefing": v1.briefing(a),
            "resources": {k: getattr(state, k) for k in RESOURCES},
        }
        for a, state in world.actors.items()
    }
    data["places"] = {}
    for r, region in world.regions.items():
        place = {
            "name": region.name,
            "owner": region.owner,
            "adjacency": list(region.adjacency),
            "attrs": {
                "control": region.control,
                "infrastructure": region.infrastructure,
                "civilian_distress": region.civilian_distress,
                "population": region.population,
                "terrain": region.terrain,
                "country": region.country,
                "lat": region.centroid[0],
                "lon": region.centroid[1],
            },
        }
        if raw["regions"][r].get("source"):
            place["source"] = raw["regions"][r]["source"]
        data["places"][r] = place
    data["entities"] = []
    for spec, force in zip(raw.get("forces") or (), world.forces, strict=True):
        entity = {
            "id": force.id,
            "owner": force.owner,
            "kind": force.kind,
            "place": force.region,
            "attrs": {
                "strength": force.strength,
                "readiness": force.readiness,
                "posture": force.posture,
            },
        }
        if spec.get("source"):
            entity["source"] = spec["source"]
        data["entities"].append(entity)
    data["display"] = DISPLAY
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=pathlib.Path, help="a v1 scenario .yaml")
    parser.add_argument("target", type=pathlib.Path, help="the v2 scenario directory to write")
    args = parser.parse_args()
    args.target.mkdir(parents=True, exist_ok=True)
    out = args.target / "scenario.yaml"
    out.write_text(
        "# Generated by tools/convert_v1_scenario.py from "
        f"{args.source.name}. Edit the data here; the physics is scenarios/reference.\n"
        + yaml.safe_dump(convert(args.source), sort_keys=False, allow_unicode=True, width=88)
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
