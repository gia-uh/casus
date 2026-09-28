"""Score a recorded run against the claims the engine makes about itself.

Three claims, from the design:

1. **Reproducibility** — the transcript replays to the same state trajectory.
2. **External branch agreement** — the branches a published analysis enumerates
   emerge from the initial conditions. Only the *ingredients* of that check live
   here; naming the branches is a question about a particular scenario and a
   particular study, and belongs with them.
3. **Physical plausibility** — the quantities the engine emits sit inside the
   ranges the scenario's `display.plausibility` declares, each with its source.

Plus the number that turned out to matter most in practice and is nobody's
claim: what fraction of everything the models declared was actually usable.
"""

from __future__ import annotations

import collections
import dataclasses
import pathlib

from . import display, engine
from .scenario import Scenario
from .state import WorldState


@dataclasses.dataclass
class Score:
    scenario: Scenario
    seed: int
    turns: int
    declared: int
    rejected: int
    rejection_reasons: dict[str, int]
    rungs: dict[str, int]
    final: WorldState
    reproducible: bool
    replayable: bool = True
    replay_error: str = ""
    plausibility: list[tuple[str, bool, str]] = dataclasses.field(default_factory=list)

    @property
    def validity(self) -> float:
        """Fraction of declared actions the resolver accepted."""
        if not self.declared:
            return 0.0
        return 1.0 - self.rejected / self.declared


def score(path: pathlib.Path | str) -> Score:
    records = engine.read_records(path)
    header = next(r for r in records if r["kind"] == "scenario")
    scenario = Scenario.from_parts(header["scenario"], header["rules_source"])
    states = sorted((r for r in records if r["kind"] == "state"), key=lambda r: r["turn"])
    final = WorldState.from_json(states[-1]["state"])

    declared = [r for r in records if r["kind"] == "action"]
    rejections = [
        r["event"]["detail"]
        for r in records
        if r["kind"] == "event" and r["event"]["id"] == "action_rejected"
    ]

    # A transcript with no `declaration` records cannot be replayed. Saying so is
    # honest; reporting it as a failed replay would read as a defect in the engine
    # rather than in the artifact.
    replayable = any(r["kind"] == "declaration" for r in records)
    reproducible, replay_error = True, ""
    if not replayable:
        reproducible, replay_error = False, "transcript predates the replayable format"
    else:
        try:
            engine.replay(path)
        except engine.ReplayMismatch as exc:
            reproducible, replay_error = False, str(exc)

    return Score(
        scenario=scenario,
        seed=int(header["seed"]),
        turns=len(states) - 1,
        declared=len(declared),
        rejected=len(rejections),
        rejection_reasons=dict(
            collections.Counter(
                _reason_family(r.get("reason", "")) for r in rejections
            ).most_common()
        ),
        rungs=_rungs(scenario, final),
        final=final,
        reproducible=reproducible,
        replayable=replayable,
        replay_error=replay_error,
        plausibility=_plausibility(scenario, final),
    )


def _reason_family(reason: str) -> str:
    """Strip the quoted specifics so reasons group by cause, not by instance."""
    return reason.split("'")[0].strip() or reason


def _rungs(scenario: Scenario, final: WorldState) -> dict[str, int]:
    resource = (scenario.display.get("ladder") or {}).get("resource")
    if not resource:
        return {}
    return {
        a: int(actor.resources[resource])
        for a, actor in sorted(final.actors.items())
        if resource in actor.resources
    }


def _plausibility(scenario: Scenario, final: WorldState) -> list[tuple[str, bool, str]]:
    """Each declared range, checked against every holder of that quantity.

    Returns (what was checked, whether it held, what was seen). A failure is a
    finding about the model, not a reason to stop.
    """
    checks: list[tuple[str, bool, str]] = []
    ranges = scenario.display.get("plausibility") or {}
    holders = [(f"{a.id}", a.resources) for a in final.actors.values()]
    holders += [(p.name, p.attrs) for p in final.places.values()]
    for name, spec in ranges.items():
        lo = float(spec.get("min", float("-inf")))
        hi = float(spec.get("max", float("inf")))
        source = spec.get("source", "unsourced")
        for holder, values in holders:
            if name not in values:
                continue
            value = float(values[name])
            checks.append(
                (
                    f"{holder}: {name} inside [{lo:g}, {hi:g}] ({source})",
                    lo <= value <= hi,
                    display.number(value),
                )
            )
    return checks


def report(score_: Score) -> str:
    """A markdown report. The audience is a reader deciding whether to believe
    the run, so every claim carries the number behind it."""
    scenario = score_.scenario
    lines = [
        f"# {scenario.name}, seed {score_.seed}",
        "",
        f"{score_.turns} turns.",
        "",
        "## Declaration validity",
        "",
        (
            f"{score_.declared} actions declared, {score_.rejected} rejected by the "
            f"resolver — {score_.validity:.0%} usable."
        ),
    ]
    if score_.rejection_reasons:
        lines += ["", "| rejected because | times |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in score_.rejection_reasons.items()]

    lines += [
        "",
        "## Reproducibility",
        "",
        (
            "The transcript replays to the same state trajectory."
            if score_.reproducible
            else (
                f"Not checkable: {score_.replay_error}."
                if not score_.replayable
                else f"**Replay failed.** {score_.replay_error}"
            )
        ),
    ]

    if score_.rungs:
        lines += ["", "## Escalation reached", "", "| actor | rung | |", "|---|---|---|"]
        lines += [
            f"| {actor} | {rung} | {display.rung_label(scenario, rung) or ''} |"
            for actor, rung in score_.rungs.items()
        ]

    standing = display.standing(scenario)
    lines += [
        "",
        "## Final standing",
        "",
        "| actor | " + " | ".join(display.label(scenario, k) for k in standing) + " |",
        "|---|" + "---|" * len(standing),
    ]
    for actor in score_.final.actors.values():
        cells = [display.number(actor.resources.get(k, float("nan"))) for k in standing]
        lines.append(f"| {actor.id} | " + " | ".join(cells) + " |")

    lines += ["", "## Physical plausibility", ""]
    for what, held, seen in score_.plausibility:
        lines.append(f"- {'✓' if held else '✗'} {what} — {seen}")

    return "\n".join(lines) + "\n"
