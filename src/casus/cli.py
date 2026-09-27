"""Command line: run a scenario, replay a transcript, verify one."""

from __future__ import annotations

import argparse
import pathlib
import sys

from . import engine, narrator
from .scenario import Scenario, ScenarioError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="casus", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="play a scenario against the configured endpoint")
    run_cmd.add_argument("scenario")
    run_cmd.add_argument("--seed", type=int, default=1)
    run_cmd.add_argument(
        "--out", default=None, help="transcript path (default runs/<name>-<seed>.jsonl)"
    )
    run_cmd.add_argument(
        "--turns", type=int, default=None, help="override the scenario's turn count"
    )
    run_cmd.add_argument(
        "--no-narrate",
        action="store_true",
        help="skip the per-turn news ticker (one fewer model call per turn)",
    )

    replay_cmd = sub.add_parser("replay", help="re-derive a run from its transcript")
    replay_cmd.add_argument("transcript")

    verify_cmd = sub.add_parser("verify", help="replay and assert every state matches")
    verify_cmd.add_argument("transcript")

    args = parser.parse_args(argv)

    if args.command == "run":
        return _run(args)
    return _verify(args.transcript, quiet=args.command == "replay")


def _run(args) -> int:
    try:
        scenario = Scenario.load(args.scenario)
    except (ScenarioError, OSError) as exc:
        print(f"casus: {exc}", file=sys.stderr)
        return 2

    out = (
        pathlib.Path(args.out)
        if args.out
        else pathlib.Path("runs") / f"{scenario.name}-{args.seed}.jsonl"
    )
    print(f"casus: {scenario.name}, seed {args.seed}, {args.turns or scenario.turns} turns")
    narrate = None
    if not args.no_narrate:
        model = str(scenario.raw.get("narrator_model", "")) or ""

        def narrate(state, resolutions):
            return narrator.narrate(state, resolutions, model=model)

    summary = engine.run(scenario, seed=args.seed, out=out, turns=args.turns, narrate=narrate)

    print(f"casus: wrote {out}")
    print(
        f"casus: {summary.turns} turns, tokens {summary.prompt_tokens}/"
        f"{summary.completion_tokens}, schema failures {summary.schema_failures}"
    )
    for actor_id, actor in sorted(summary.final.actors.items()):
        print(
            f"  {actor_id}: rung {actor.escalation_rung}, fuel {actor.fuel_days:.0f}d, "
            f"legitimacy {actor.intl_legitimacy:.0f}, support {actor.domestic_support:.0f}"
        )
    return 0


def _verify(transcript: str, quiet: bool) -> int:
    try:
        summary = engine.replay(transcript)
    except engine.ReplayMismatch as exc:
        print(f"casus: REPLAY FAILED — {exc}", file=sys.stderr)
        return 1
    if not quiet:
        print(f"casus: replay OK — {summary.turns} turns, every state digest matches")
    else:
        print(f"casus: {summary.scenario}, {summary.turns} turns replayed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
