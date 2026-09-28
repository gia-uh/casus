"""Score a recorded run against the claims the engine makes about itself.

Three claims, from the design:

1. **Reproducibility** — the transcript replays to the same state trajectory.
2. **External branch agreement** — the branches a published analysis enumerates
   emerge from the initial conditions. Only the *ingredients* of that check live
   here; naming the branches is a question about a particular scenario and a
   particular study, and belongs with them.
3. **Physical plausibility** — the quantities the engine emits sit inside ranges
   public sources give.

Plus the number that turned out to matter most in practice and is nobody's
claim: what fraction of everything the models declared was actually usable.
"""

from __future__ import annotations

import collections
import dataclasses
import pathlib

from . import engine
from .v1 import rules
from .v1.state import RUNG_NAMES, WorldState


@dataclasses.dataclass
class Score:
    scenario: str
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
    states = sorted((r for r in records if r["kind"] == "state"), key=lambda r: r["turn"])
    final = WorldState.from_json(states[-1]["state"])

    declared = [r for r in records if r["kind"] == "action"]
    rejections = [
        r["resolution"]
        for r in records
        if r["kind"] == "resolution" and r["resolution"]["kind"] == "action_rejected"
    ]

    # A transcript with no `declaration` records predates the current format and
    # cannot be replayed. Saying so is honest; reporting it as a failed replay
    # would read as a defect in the engine rather than in the artifact.
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
        scenario=header["name"],
        seed=int(header["seed"]),
        turns=len(states) - 1,
        declared=len(declared),
        rejected=len(rejections),
        rejection_reasons=dict(
            collections.Counter(_reason_family(r["reason"]) for r in rejections).most_common()
        ),
        rungs={a: s.escalation_rung for a, s in sorted(final.actors.items())},
        final=final,
        reproducible=reproducible,
        replayable=replayable,
        replay_error=replay_error,
        plausibility=_plausibility(final),
    )


def _reason_family(reason: str) -> str:
    """Strip the quoted specifics so reasons group by cause, not by instance."""
    return reason.split("'")[0].strip() or reason


def _plausibility(final: WorldState) -> list[tuple[str, bool, str]]:
    """Checks whose expected ranges come from the published record.

    Each returns (what was checked, whether it held, what was seen). A failure is
    a finding about the model, not a reason to stop.
    """
    checks: list[tuple[str, bool, str]] = []

    for region in final.regions.values():
        if region.population <= 0 or not region.country:
            continue
        if region.owner in ("", region.country):
            continue
        required = rules.occupation_requirement(region.population)
        present = (
            sum(
                f.strength
                for f in final.forces
                if f.owner == region.owner
                and f.kind in ("ground", "irregular")
                and f.region == region.id
            )
            * rules.TROOPS_PER_STRENGTH_POINT
        )
        checks.append(
            (
                f"{region.name} is occupied with the ratio the literature requires",
                present >= required,
                f"{present:,.0f} present against {required:,} required",
            )
        )

    for actor in final.actors.values():
        checks.append(
            (
                f"{actor.id} stayed inside the 0–100 bands",
                all(
                    0.0 <= v <= 100.0
                    for v in (
                        actor.intl_legitimacy,
                        actor.domestic_support,
                        actor.political_capital,
                    )
                ),
                f"legitimacy {actor.intl_legitimacy:.0f}, support {actor.domestic_support:.0f}",
            )
        )
        checks.append(
            (
                f"{actor.id} never went into negative fuel",
                actor.fuel_days >= 0.0,
                f"{actor.fuel_days:.0f} fuel-days",
            ),
        )

    return checks


def report(score_: Score) -> str:
    """A markdown report. The audience is a reader deciding whether to believe
    the run, so every claim carries the number behind it."""
    lines = [
        f"# {score_.scenario}, seed {score_.seed}",
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
        "",
        "## Escalation reached",
        "",
        "| actor | rung | |",
        "|---|---|---|",
    ]
    lines += [
        f"| {actor} | {rung} | {RUNG_NAMES[rung]} |" for actor, rung in score_.rungs.items()
    ]

    lines += [
        "",
        "## Final standing",
        "",
        "| actor | fuel-days | legitimacy | support |",
        "|---|---|---|---|",
    ]
    for actor in score_.final.actors.values():
        lines.append(
            f"| {actor.id} | {actor.fuel_days:.0f} | {actor.intl_legitimacy:.0f} | "
            f"{actor.domestic_support:.0f} |"
        )

    lines += ["", "## Physical plausibility", ""]
    for what, held, seen in score_.plausibility:
        lines.append(f"- {'✓' if held else '✗'} {what} — {seen}")

    return "\n".join(lines) + "\n"
