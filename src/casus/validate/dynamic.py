"""A dry run, played for real: what reading the source cannot show.

Every actor holds for the requested turns, then declares each action type it is
offered in turn, and `offer` and `view` run for every actor every turn, so every
rule and hook executes. The dry run reports a rule that names something the scenario
does not declare, a rule written for an action type nobody can declare, a rule
that changes module state, and a value the ledger does not account for, and a
trajectory that does not come out the same in two processes started with
different hash seeds. The last is the check that needs
two processes: string hashing, and so the iteration order of a set, is fixed
for the life of one.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import json
import os
import random
import subprocess
import sys

from ..players import believed, offered_actions
from ..proxy import Mutation, UnknownName
from ..resolver import RuleFailed, resolve
from ..scenario import Scenario
from ..state import WorldState
from . import Finding
from .ledger import first_unrecorded
from .policy import cover, holding

#: Two hash seeds that give different string orders.
HASH_SEEDS = ("1", "2")


@dataclasses.dataclass
class DryRunReport:
    findings: list[Finding]
    trajectory: list[str]
    ledger: list[Mutation]


def trajectory(scenario: Scenario, turns: int, seed: int = 0):
    """Play `turns` holding turns, then one cover turn per declared action type,
    calling `offer` and `view` for every actor each turn as the engine does.

    Returns the digests, the ledger, the failure that stopped the run if one did,
    and the first value the ledger does not account for ('' if none).
    """
    rng = random.Random(seed)
    choices = random.Random(seed + 7919)
    world: WorldState = scenario.initial_state()
    start = world.to_json()
    digests, ledger = [world.digest()], []
    plan = [holding] * turns + [cover] * max(1, len(scenario.actions))
    for index, policy in enumerate(plan):
        try:
            for actor in sorted(scenario.actors):
                believed(scenario, world, actor, rng)
                offered_actions(scenario, world, actor, rng)
            world, _, mutations = resolve(
                world,
                policy(scenario, world, choices, index - turns),
                scenario.ruleset,
                rng,
                scenario.actions,
                scenario.resource_bounds(),
                scenario.attribute_bounds(),
            )
        except RuleFailed as exc:
            return digests, ledger, exc, ""
        digests.append(world.digest())
        ledger.extend(mutations)
    unrecorded = first_unrecorded(start, [m.to_json() for m in ledger], world.to_json())
    return digests, ledger, None, unrecorded


def dry_run(scenario: Scenario, turns: int = 1, seed: int = 0) -> DryRunReport:
    findings = _unknown_actions(scenario)
    before = _mutable_globals(scenario)
    digests, ledger, failure, unrecorded = trajectory(scenario, turns, seed)
    if failure is not None:
        findings.append(_finding_for(failure, scenario))
        return DryRunReport(findings, digests, ledger)
    if unrecorded:
        findings.append(
            Finding(
                "ledger-mismatch",
                f"{unrecorded}: something changed state without going through the "
                "mutation calls, so the ledger no longer says what happened",
                scenario.origin,
            )
        )
    findings += _module_state(scenario, before)
    findings += _cross_process(scenario, turns, seed)
    return DryRunReport(findings, digests, ledger)


def _unknown_actions(scenario: Scenario) -> list[Finding]:
    out = []
    for r in scenario.ruleset.rules:
        for action_type in r.on or ():
            if action_type not in scenario.actions:
                out.append(
                    Finding(
                        "unknown-action",
                        f"rule '{r.name}' runs on '{action_type}', which the scenario "
                        "does not declare, so it can never run",
                        scenario.origin,
                    )
                )
    return out


def _finding_for(failure: RuleFailed, scenario: Scenario) -> Finding:
    cause = failure.__cause__
    if isinstance(cause, UnknownName):
        return Finding(f"unknown-{cause.kind}", f"{failure}", scenario.origin)
    return Finding("rule-error", str(failure), scenario.origin)


def _mutable_globals(scenario: Scenario) -> dict[str, object]:
    module = scenario.module
    if module is None:
        return {}
    return {
        k: copy.deepcopy(v)
        for k, v in vars(module).items()
        if not k.startswith("__") and isinstance(v, list | dict | set | bytearray)
    }


def _module_state(scenario: Scenario, before: dict[str, object]) -> list[Finding]:
    after = _mutable_globals(scenario)
    changed = sorted(k for k in before if before[k] != after.get(k))
    if not changed:
        return []
    return [
        Finding(
            "module-state",
            f"a dry turn changed module-level {', '.join(changed)}; a rule may keep "
            "state only in the world",
            scenario.origin,
        )
    ]


#: Cross-process results by scenario content. The check costs two interpreter
#: starts and its answer depends only on the data, the rules, the turns and the
#: seed, so one process never pays twice for the same scenario.
_CROSS_PROCESS: dict[str, list[Finding]] = {}


def _cross_process(scenario: Scenario, turns: int, seed: int) -> list[Finding]:
    key = json.dumps([scenario.data, scenario.rules_source, turns, seed], sort_keys=True)
    if key not in _CROSS_PROCESS:
        _CROSS_PROCESS[key] = _run_cross_process(scenario, turns, seed)
    return list(_CROSS_PROCESS[key])


def _run_cross_process(scenario: Scenario, turns: int, seed: int) -> list[Finding]:
    payload = json.dumps(
        {"data": scenario.data, "rules_source": scenario.rules_source, "turns": turns,
         "seed": seed}
    )  # fmt: skip
    # Both processes at once: each pays an interpreter start, and they share nothing.
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "casus.validate.dynamic"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
        )
        for hash_seed in HASH_SEEDS
    ]
    runs = []
    for proc in procs:
        out, err = proc.communicate(payload)
        if proc.returncode != 0:
            return [Finding("rule-error", err.strip()[-400:], scenario.origin)]
        runs.append(json.loads(out))
    first, second = runs
    for turn, (a, b) in enumerate(zip(first, second, strict=True)):
        if a != b:
            return [
                Finding(
                    "nondeterministic",
                    f"turn {turn} differs between two processes with different hash "
                    "seeds; a rule iterates a set or orders by hash. Sort it.",
                    scenario.origin,
                )
            ]
    return []


def _main() -> int:
    """Subprocess entry: print the dry trajectory's digests for a scenario on stdin."""
    job = json.loads(sys.stdin.read())
    scenario = Scenario.from_parts(job["data"], job["rules_source"])
    # A rule's print() would otherwise land in front of the digests on stdout.
    with contextlib.redirect_stdout(sys.stderr):
        digests, _, failure, _ = trajectory(scenario, job["turns"], job["seed"])
    if failure is not None:
        print(str(failure), file=sys.stderr)
        return 1
    print(json.dumps(digests))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
