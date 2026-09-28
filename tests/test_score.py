import pathlib

from casus import score
from casus.v1 import engine
from casus.v1.scenario import Scenario
from helpers import FakeEngine, scripted

SMOKE = pathlib.Path(__file__).parent.parent / "scenarios" / "smoke.yaml"


def _run(tmp_path, reply=None, turns=2):
    scenario = Scenario.load(SMOKE)
    out = tmp_path / "run.jsonl"
    engine.run(
        scenario,
        seed=3,
        out=out,
        engines={a: FakeEngine(reply) for a in scenario.actors},
        turns=turns,
    )
    return out


def test_a_clean_run_scores_full_validity(tmp_path):
    result = score.score(_run(tmp_path))
    assert result.declared > 0
    assert result.rejected == 0
    assert result.validity == 1.0


def test_rejections_are_counted_and_grouped_by_cause(tmp_path):
    """Two rejections for the same reason with different specifics have to land
    in one bucket, or the table is a list of instances rather than causes."""
    out = _run(
        tmp_path,
        reply=scripted(
            {
                "BLUE": {
                    "actions": [{"type": "invade", "region": "g-capital"}],
                    "rationale": "go",
                    "assessment": "",
                }
            }
        ),
    )
    result = score.score(out)
    assert result.rejected > 0
    assert result.validity < 1.0
    assert any("within reach" in reason for reason in result.rejection_reasons)


def test_reproducibility_is_checked_by_actually_replaying(tmp_path):
    result = score.score(_run(tmp_path))
    assert result.reproducible
    assert result.replay_error == ""


def test_a_tampered_transcript_scores_as_not_reproducible(tmp_path):
    import json

    from casus.v1.state import WorldState

    out = _run(tmp_path)
    lines = []
    for line in out.read_text().splitlines():
        record = json.loads(line)
        if record["kind"] == "state" and record["turn"] == 2:
            actor = min(record["state"]["actors"])
            record["state"]["actors"][actor]["fuel_days"] += 7.0
            record["digest"] = WorldState.from_json(record["state"]).digest()
        lines.append(json.dumps(record))
    out.write_text("\n".join(lines) + "\n")

    result = score.score(out)
    assert not result.reproducible
    assert "turn 2" in result.replay_error


def test_the_report_carries_the_number_behind_every_claim(tmp_path):
    text = score.report(score.score(_run(tmp_path)))
    assert "Declaration validity" in text
    assert "usable" in text
    assert "Reproducibility" in text
    assert "Escalation reached" in text
    assert "Physical plausibility" in text


def test_the_rungs_come_from_the_final_state_not_from_the_actions(tmp_path):
    out = _run(
        tmp_path,
        reply=scripted(
            {
                "BLUE": {
                    "actions": [{"type": "blockade", "region": "strait"}],
                    "rationale": "squeeze",
                    "assessment": "",
                }
            }
        ),
    )
    result = score.score(out)
    assert result.rungs["BLUE"] >= 3
    assert result.rungs["BLUE"] == result.final.actors["BLUE"].escalation_rung


def test_plausibility_reports_every_check_it_ran(tmp_path):
    result = score.score(_run(tmp_path))
    assert result.plausibility
    assert all(isinstance(held, bool) for _, held, _ in result.plausibility)


def test_a_transcript_that_predates_the_format_says_so_instead_of_failing(tmp_path):
    """Reporting an old artifact as a failed replay would read as a defect in the
    engine rather than in the artifact."""
    import json

    out = _run(tmp_path)
    kept = [r for r in engine.read_records(out) if r["kind"] != "declaration"]
    out.write_text("\n".join(json.dumps(r) for r in kept) + "\n")

    result = score.score(out)
    assert not result.replayable
    assert not result.reproducible
    assert "predates" in result.replay_error
    assert "Not checkable" in score.report(result)
