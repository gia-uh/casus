"""The viewer's data layer, run under node without a browser."""

import json
import pathlib
import shutil
import subprocess

import pytest

from casus import bundle, engine
from casus.scenario import Scenario
from helpers import FakeEngine

ROOT = pathlib.Path(__file__).parent.parent
HARNESS = ROOT / "tests" / "js" / "harness.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _records(tmp_path, turns=2):
    scenario = Scenario.load(ROOT / "scenarios" / "smoke")
    out = tmp_path / "run.jsonl"
    engines = {a: FakeEngine() for a in scenario.actors}
    engine.run(scenario, seed=1, out=out, engines=engines, turns=turns)
    return bundle.viewer_records(engine.read_records(out))


def _model(records, labels=()):
    payload = json.dumps({"records": records, "labels": list(labels)})
    done = subprocess.run(
        [NODE, str(HARNESS), "i18n.js,records.js"],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_complete_run_folds_into_its_playable_turns(tmp_path):
    records = _records(tmp_path, turns=2)
    model = _model(records)
    assert model["scenario"] == "smoke"
    assert model["playable"] == [1, 2]
    assert model["complete"] == [True, True]
    assert model["ended"] is True
    assert model["actors"] == ["BLUE", "RED"]
    assert model["declared"] == [["BLUE", "RED"], ["BLUE", "RED"]]


def test_mutation_counts_come_from_the_ledger_records(tmp_path):
    records = _records(tmp_path, turns=2)
    expected = [r["mutations"] for r in records if r["kind"] == "ledger"]
    assert _model(records)["mutations"] == expected


def test_a_run_cut_before_its_last_state_leaves_that_turn_incomplete(tmp_path):
    records = _records(tmp_path, turns=2)
    last_state = max(i for i, r in enumerate(records) if r["kind"] == "state")
    model = _model(records[:last_state])
    assert model["complete"] == [True, False]
    assert model["ended"] is False


def test_labels_fall_back_from_display_to_names_to_ids(tmp_path):
    model = _model(_records(tmp_path), labels=["BLUE", "border", "no_such_thing"])
    assert model["labels"] == ["Blue", "The Border", "no such thing"]


def _card(records, place, sealed=False):
    payload = json.dumps({"records": records, "labels": [], "card": place, "sealed": sealed})
    done = subprocess.run(
        [NODE, str(HARNESS), "i18n.js,records.js,map.js,card.js"],
        input=payload, capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)["card"]


def test_the_card_names_the_place_its_holder_and_its_neighbours(tmp_path):
    html = _card(_records(tmp_path), "border")
    assert "The Border" in html
    assert "Red" in html
    assert "Blue Home" in html and "Red Home" in html


def test_a_sealed_turn_does_not_reveal_what_was_aimed_at_the_place(tmp_path):
    html = _card(_records(tmp_path), "border", sealed=True)
    assert "the declarations are still sealed" in html


def test_the_card_shows_before_and_after_for_card_attributes(tmp_path):
    html = _card(_records(tmp_path), "border")
    assert "infra" in html


@pytest.mark.parametrize("name", sorted(p.name for p in (ROOT / "ui" / "js").glob("*.js")))
def test_every_ui_script_parses(name):
    """The scripts are classic so the bundle can concatenate them. node --check
    exits 0 on a .js file in ES module syntax even with a syntax error, so this
    test relies on ui/ staying classic."""
    done = subprocess.run(
        [NODE, "--check", str(ROOT / "ui" / "js" / name)], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr[:400]


def test_viewer_js_exists():
    assert (ROOT / "ui" / "js" / "viewer.js").is_file()
