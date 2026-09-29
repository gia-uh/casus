import json
import pathlib

from casus import engine, studies
from casus.scenario import Scenario
from helpers import FakeEngine

SMOKE = pathlib.Path(__file__).parent.parent / "scenarios" / "smoke"


def _run(runs_dir: pathlib.Path, seed: int, turns: int = 2) -> pathlib.Path:
    scenario = Scenario.load(SMOKE)
    out = runs_dir / f"smoke-{seed}.jsonl"
    engines = {a: FakeEngine() for a in scenario.actors}
    engine.run(scenario, seed=seed, out=out, engines=engines, turns=turns)
    return out


def test_a_complete_run_is_listed_with_its_seed_and_turns(tmp_path):
    _run(tmp_path, seed=7, turns=2)
    [info] = studies.list_runs(tmp_path)
    assert (info.id, info.scenario, info.seed) == ("smoke-7", "smoke", 7)
    assert (info.turns_planned, info.turns_done, info.status) == (2, 2, "complete")


def test_a_transcript_cut_mid_turn_is_incomplete(tmp_path):
    path = _run(tmp_path, seed=3, turns=2)
    lines = path.read_text().splitlines()
    last_state = max(i for i, line in enumerate(lines) if json.loads(line)["kind"] == "state")
    path.write_text("\n".join(lines[: last_state - 1]) + "\n")
    [info] = studies.list_runs(tmp_path)
    assert info.status == "incomplete"
    assert info.turns_done == 1


def test_a_run_that_recorded_an_error_is_failed(tmp_path):
    path = _run(tmp_path, seed=4, turns=1)
    with path.open("a") as fh:
        fh.write(json.dumps({"kind": "error", "turn": 2, "error": "boom"}) + "\n")
    [info] = studies.list_runs(tmp_path)
    assert info.status == "failed"


def test_files_that_are_not_transcripts_are_skipped(tmp_path):
    _run(tmp_path, seed=1)
    (tmp_path / "notes.jsonl").write_text("not json\n")
    (tmp_path / "empty.jsonl").write_text("")
    (tmp_path / "array.jsonl").write_text("[1, 2]\n")
    assert [i.id for i in studies.list_runs(tmp_path)] == ["smoke-1"]


def test_a_half_written_last_line_is_read_as_the_end_of_the_file(tmp_path):
    path = _run(tmp_path, seed=5, turns=2)
    lines = path.read_text().splitlines()
    last_state = max(i for i, line in enumerate(lines) if json.loads(line)["kind"] == "state")
    path.write_text("\n".join(lines[:last_state]) + '\n{"kind":"sta')
    [info] = studies.list_runs(tmp_path)
    assert (info.status, info.turns_done) == ("incomplete", 1)


def test_a_last_line_cut_inside_a_multibyte_character_is_torn(tmp_path):
    path = _run(tmp_path, seed=9, turns=2)
    lines = path.read_text().splitlines()
    last_state = max(i for i, line in enumerate(lines) if json.loads(line)["kind"] == "state")
    head = ("\n".join(lines[:last_state]) + "\n").encode()
    path.write_bytes(head + '{"kind":"state","text":"ñ'.encode()[:-1])
    [info] = studies.list_runs(tmp_path)
    assert (info.status, info.turns_done) == ("incomplete", 1)


def test_an_error_before_a_half_written_last_line_is_still_failed(tmp_path):
    path = _run(tmp_path, seed=6, turns=1)
    with path.open("a") as fh:
        fh.write(json.dumps({"kind": "error", "turn": 2, "error": "boom"}) + '\n{"kind":"sta')
    [info] = studies.list_runs(tmp_path)
    assert info.status == "failed"


def test_an_undecodable_line_before_the_last_skips_the_file(tmp_path):
    path = _run(tmp_path, seed=8, turns=2)
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], '{"kind":"sta', *lines[1:]]) + "\n")
    assert studies.list_runs(tmp_path) == []


def test_a_header_with_a_malformed_number_is_skipped(tmp_path):
    _run(tmp_path, seed=2)
    (tmp_path / "null-seed.jsonl").write_text('{"kind":"scenario","seed":null}\n')
    (tmp_path / "text-seed.jsonl").write_text('{"kind":"scenario","seed":"x"}\n')
    (tmp_path / "inf-seed.jsonl").write_text('{"kind":"scenario","seed":Infinity}\n')
    assert [i.id for i in studies.list_runs(tmp_path)] == ["smoke-2"]
