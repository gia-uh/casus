"""The decorators a scenario's `rules.py` uses, and the registry built from them.

A rule is a function decorated with `@rule(phase=..., on=...)`. Rules run in the
five phases in a fixed order, and in declaration order within a phase. A rule
with `on=` (one action type or a tuple of them) runs once per matching action and
receives it; a rule without runs once per turn and reads `s.actions` if it needs
them.

`@offer` and `@view` are the player-side hooks: what an actor may declare, and
what it believes the world looks like.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from types import ModuleType

PHASES = ("legality", "upkeep", "movement", "contest", "consequences")

_RULE = "_casus_rule"
_HOOK = "_casus_hook"


@dataclasses.dataclass(frozen=True)
class Rule:
    name: str
    phase: str
    on: tuple[str, ...] | None
    fn: Callable


def rule(phase: str, on: str | tuple[str, ...] | None = None) -> Callable[[Callable], Callable]:
    if phase not in PHASES:
        raise ValueError(f"unknown phase '{phase}'; the phases are {', '.join(PHASES)}")

    def decorate(fn: Callable) -> Callable:
        types_ = (on,) if isinstance(on, str) else (tuple(on) if on else None)
        setattr(fn, _RULE, Rule(name=fn.__name__, phase=phase, on=types_, fn=fn))
        return fn

    return decorate


def offer(fn: Callable) -> Callable:
    setattr(fn, _HOOK, "offer")
    return fn


def view(fn: Callable) -> Callable:
    setattr(fn, _HOOK, "view")
    return fn


@dataclasses.dataclass(frozen=True)
class RuleSet:
    rules: tuple[Rule, ...]
    offer: Callable | None = None
    view: Callable | None = None

    @classmethod
    def from_module(cls, module: ModuleType) -> RuleSet:
        rules: list[Rule] = []
        hooks: dict[str, list[Callable]] = {"offer": [], "view": []}
        for value in vars(module).values():
            found = getattr(value, _RULE, None)
            if isinstance(found, Rule):
                rules.append(found)
            hook = getattr(value, _HOOK, None)
            if hook in hooks:
                hooks[hook].append(value)
        for name, fns in hooks.items():
            if len(fns) > 1:
                names = ", ".join(f.__name__ for f in fns)
                raise ValueError(f"a scenario declares at most one @{name}; found {names}")
        return cls(
            rules=tuple(rules),
            offer=hooks["offer"][0] if hooks["offer"] else None,
            view=hooks["view"][0] if hooks["view"] else None,
        )

    def for_phase(self, phase: str) -> tuple[Rule, ...]:
        return tuple(r for r in self.rules if r.phase == phase)
