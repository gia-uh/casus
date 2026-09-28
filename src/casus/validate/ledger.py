"""Replay a ledger onto a state, to check that it says everything that happened.

If applying every recorded mutation to the starting state does not land on the
final state, some path changed a value without going through the proxy, and the
ledger no longer answers "what moved this number".
"""

from __future__ import annotations

import copy
from typing import Any


def apply(state: dict[str, Any], mutation: dict[str, Any]) -> None:
    scope, ident, *rest = mutation["ref"].split(".", 2)
    if scope == "entity" and not rest:
        if mutation["after"] is None:
            state["entities"][:] = [e for e in state["entities"] if e["id"] != ident]
        else:
            state["entities"].append(copy.deepcopy(mutation["after"]))
        return
    (name,) = rest
    if scope == "actor":
        state["actors"][ident]["resources"][name] = mutation["after"]
    elif scope == "place":
        state["places"][ident]["attrs"][name] = mutation["after"]
    else:
        entity = next(e for e in state["entities"] if e["id"] == ident)
        if name == "place":
            entity["place"] = mutation["after"]
        else:
            entity["attrs"][name] = mutation["after"]


def _flatten(value: Any, path: str, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(v, f"{path}.{k}" if path else str(k), out)
    elif isinstance(value, list) and path == "entities":
        for e in value:
            _flatten(e, f"entity.{e['id']}", out)
    else:
        out[path] = value


def _paths(state: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for scope, key in (("actors", "actor"), ("places", "place")):
        for ident, record in state[scope].items():
            _flatten(record, f"{key}.{ident}", out)
    _flatten(state["entities"], "entities", out)
    return {p.replace(".resources.", ".").replace(".attrs.", "."): v for p, v in out.items()}


def first_unrecorded(
    start: dict[str, Any], mutations: list[dict], final: dict[str, Any]
) -> str:
    """The first path where the final state differs from start + ledger, or ''."""
    rebuilt = copy.deepcopy(start)
    for mutation in mutations:
        apply(rebuilt, mutation)
    a, b = _paths(rebuilt), _paths(final)
    for path in sorted(set(a) | set(b)):
        if a.get(path) != b.get(path):
            return f"{path} is {b.get(path)!r} but the ledger says {a.get(path)!r}"
    return ""
