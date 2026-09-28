"""Command line: run a scenario, replay a transcript, verify one."""

from __future__ import annotations

import argparse
import pathlib
import sys

from . import bundle as bundle_mod
from . import engine
from . import score as score_mod
from .v1.scenario import Scenario, ScenarioError


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

    bundle_cmd = sub.add_parser("bundle", help="write a self-contained HTML replayer")
    bundle_cmd.add_argument("transcript")
    bundle_cmd.add_argument("--out", default=None)

    score_cmd = sub.add_parser("score", help="score a run against the engine's own claims")
    score_cmd.add_argument("transcript")
    score_cmd.add_argument(
        "--out", default=None, help="write the report here instead of stdout"
    )

    args = parser.parse_args(argv)

    if args.command == "run":
        return _run(args)
    if args.command == "bundle":
        return _bundle(args)
    if args.command == "score":
        return _score(args)
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
    narrator_engine = (
        None
        if args.no_narrate
        else engine.engine_for(
            scenario.narrator_model() or scenario.model(next(iter(scenario.actors)))
        )
    )
    summary = engine.run(
        scenario,
        seed=args.seed,
        out=out,
        turns=args.turns,
        narrator_engine=narrator_engine,
    )

    print(f"casus: wrote {out}")
    print(f"casus: {summary.turns} turns")
    for actor_id, actor in sorted(summary.final.actors.items()):
        print(
            f"  {actor_id}: rung {actor.escalation_rung}, fuel {actor.fuel_days:.0f}d, "
            f"legitimacy {actor.intl_legitimacy:.0f}, support {actor.domestic_support:.0f}"
        )
    return 0


def _bundle(args) -> int:
    source = pathlib.Path(args.transcript)
    out = pathlib.Path(args.out) if args.out else source.with_suffix(".html")
    try:
        written = bundle_mod.bundle(source, out)
    except (bundle_mod.BundleError, OSError) as exc:
        print(f"casus: {exc}", file=sys.stderr)
        return 2
    size = written.stat().st_size
    print(f"casus: wrote {written} — {size / 1024:.0f} KiB, self-contained")
    print("casus: open it in a browser and step the turns with the arrow keys")
    return 0


def _score(args) -> int:
    result = score_mod.score(args.transcript)
    text = score_mod.report(result)
    if args.out:
        pathlib.Path(args.out).write_text(text)
        print(f"casus: wrote {args.out}")
    else:
        print(text)
    return 0 if result.reproducible else 1


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
