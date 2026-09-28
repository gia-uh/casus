"""How the engine shows a scenario's quantities without knowing what they mean.

Everything here reads the scenario's `display` block: labels in the scenario's
language, bands that stand in for an exact number, which attributes stay off the
page, and the escalation ladder if the scenario has one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .scenario import Scenario

DEFAULT_HIDDEN = ("lat", "lon")


def label(scenario: Scenario, name: str) -> str:
    labels = (scenario.display.get("labels") or {}).get(scenario.language()) or {}
    return str(labels.get(name) or name.replace("_", " "))


def band(scenario: Scenario, name: str, value: float) -> str | None:
    """The first band whose upper bound the value is below, or None."""
    bands = (scenario.display.get("bands") or {}).get(name)
    if not bands:
        return None
    for bound, text in sorted(bands.items(), key=lambda item: float(item[0])):
        if float(value) < float(bound):
            return str(text)
    return None


def number(value: Any) -> str:
    if isinstance(value, str):
        return value
    value = float(value)
    if value.is_integer() or abs(value) >= 10:
        return f"{value:.0f}"
    return f"{value:.2f}"


def shown(scenario: Scenario, name: str, value: Any, exact: bool) -> str:
    """An exact figure with its band beside it, or only the band when the reader
    is not entitled to the figure."""
    banded = None if isinstance(value, str) else band(scenario, name, value)
    if banded is None:
        return number(value)
    return f"{number(value)} ({banded})" if exact else banded


def hidden(scenario: Scenario) -> tuple[str, ...]:
    return tuple(scenario.display.get("hidden") or DEFAULT_HIDDEN)


def standing(scenario: Scenario) -> tuple[str, ...]:
    return tuple(scenario.display.get("standing") or tuple(scenario.resources))


def attributes(scenario: Scenario, attrs: dict[str, Any]) -> str:
    skip = set(hidden(scenario))
    return ", ".join(
        f"{label(scenario, k)} {number(v)}" for k, v in attrs.items() if k not in skip
    )


def rung_label(scenario: Scenario, rung: int) -> str | None:
    ladder = scenario.display.get("ladder") or {}
    names = ladder.get(scenario.language()) or ladder.get("en")
    if not names or not 0 <= int(rung) < len(names):
        return None
    return str(names[int(rung)])
