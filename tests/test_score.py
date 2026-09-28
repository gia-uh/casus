"""Score a recorded run against the claims the engine makes about itself."""

import json

from scenariopaths import SCENARIOS

from casus import engine, score
from casus.scenario import Scenario
from helpers import FakeEngine, scripted

REFERENCE = SCENARIOS / "reference"


def _run(tmp_path, reply=None, turns=2):
    scenario = Scenario.load(REFERENCE)
    out = tmp_path / "run.jsonl"
    engine.run(
        scenario, seed=3, out=out, engines={a: FakeEngine(reply) for a in scenario.actors},
        turns=turns,
    )  # fmt: skip
    return out


def _blue(action):
    return scripted({"BLUE": {"actions": [action], "rationale": "go", "assessment": ""}})


def test_a_clean_run_scores_full_validity(tmp_path):
    result = score.score(_run(tmp_path))
    assert result.declared > 0
    assert result.rejected == 0
    assert result.validity == 1.0


def test_rejections_are_counted_and_grouped_by_cause(tmp_path):
    """Rejections with different specifics but one cause land in one bucket, or
    the table is a list of instances rather than causes. v2's schemas make
    rejections rare, so the transcript gets two written into it."""
    out = _run(tmp_path)
    extra = [
        {"kind": "event", "turn": 1, "event": {"id": "action_rejected", "detail": {
            "actor": "BLUE", "reason": f"no strike platforms within reach of '{place}'"}}}
        for place in ("g-capital", "g-interior")
    ]  # fmt: skip
    with out.open("a") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in extra)
    result = score.score(out)
    assert result.rejected == 2
    assert result.rejection_reasons == {"no strike platforms within reach of": 2}
    assert result.validity < 1.0


def test_reproducibility_is_checked_by_actually_replaying(tmp_path):
    result = score.score(_run(tmp_path))
    assert result.reproducible
    assert result.replay_error == ""


def test_a_tampered_transcript_scores_as_not_reproducible(tmp_path):
    out = _run(tmp_path)
    lines = []
    for line in out.read_text().splitlines():
        record = json.loads(line)
        if record["kind"] == "state" and record["turn"] == 2:
            actor = min(record["state"]["actors"])
            record["state"]["actors"][actor]["resources"]["fuel_days"] += 7.0
        lines.append(json.dumps(record))
    out.write_text("\n".join(lines) + "\n")
    result = score.score(out)
    assert not result.reproducible
    assert "turn 2" in result.replay_error


def test_the_report_carries_the_number_behind_every_claim(tmp_path):
    text = score.report(score.score(_run(tmp_path)))
    for section in ("Declaration validity", "usable", "Reproducibility", "Escalation reached",
                    "Final standing", "Physical plausibility"):  # fmt: skip
        assert section in text


def test_the_rungs_come_from_the_final_state_not_from_the_actions(tmp_path):
    result = score.score(_run(tmp_path, reply=_blue({"type": "blockade", "place": "strait"})))
    assert result.rungs["BLUE"] >= 3
    assert result.rungs["BLUE"] == result.final.actors["BLUE"].resources["escalation_rung"]


def test_a_scenario_without_a_ladder_reports_no_rungs(tmp_path):
    scenario = Scenario.load(SCENARIOS / "smoke")
    display = {k: v for k, v in scenario.display.items() if k != "ladder"}
    bare = Scenario.from_parts({**scenario.data, "display": display}, scenario.rules_source)
    out = tmp_path / "run.jsonl"
    engine.run(bare, seed=1, out=out, engines={a: FakeEngine() for a in bare.actors}, turns=1)
    result = score.score(out)
    assert result.rungs == {}
    assert "Escalation reached" not in score.report(result)


def test_plausibility_checks_the_declared_ranges(tmp_path):
    result = score.score(_run(tmp_path))
    assert result.plausibility
    assert all(held for _, held, _ in result.plausibility)
    assert any("domestic_support" in what for what, _, _ in result.plausibility)


def test_a_transcript_that_predates_the_format_says_so_instead_of_failing(tmp_path):
    out = _run(tmp_path)
    kept = [r for r in engine.read_records(out) if r["kind"] != "declaration"]
    out.write_text("\n".join(json.dumps(r) for r in kept) + "\n")
    result = score.score(out)
    assert not result.replayable
    assert not result.reproducible
    assert "predates" in result.replay_error
