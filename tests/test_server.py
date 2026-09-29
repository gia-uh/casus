import pathlib

import pytest
from fastapi.testclient import TestClient

from casus import engine
from casus.scenario import Scenario
from casus.server.app import create_app
from helpers import FakeEngine

ROOT = pathlib.Path(__file__).parent.parent
SCENARIOS = ROOT / "scenarios"


@pytest.fixture
def runs(tmp_path) -> pathlib.Path:
    scenario = Scenario.load(SCENARIOS / "smoke")
    engines = {a: FakeEngine() for a in scenario.actors}
    runs = tmp_path / "runs"
    engine.run(scenario, seed=5, out=runs / "smoke-5.jsonl", engines=engines, turns=2)
    return runs


@pytest.fixture
def client(runs) -> TestClient:
    return TestClient(create_app(scenarios_dir=SCENARIOS, runs_dir=runs))


def test_the_home_page_loads_the_scripts_in_order(client):
    html = client.get("/").text
    order = [
        html.index(f"/ui/js/{n}")
        for n in ("i18n.js", "records.js", "map.js", "card.js", "viewer.js", "shell.js")
    ]
    assert order == sorted(order)
    assert "casus-worldmap" in html


def test_scripts_are_served(client):
    assert client.get("/ui/js/viewer.js").status_code == 200


def test_scenarios_list_the_shipped_ones_with_their_counts(client):
    by_name = {s["name"]: s for s in client.get("/api/scenarios").json()}
    smoke = by_name["smoke"]
    assert (smoke["actors"], smoke["places"], smoke["turns"]) == (2, 3, 3)
    assert smoke["valid"] is True and smoke["findings"] == []


def test_runs_are_listed(client):
    [run] = client.get("/api/runs").json()
    assert (run["id"], run["scenario"], run["status"]) == ("smoke-5", "smoke", "complete")


def test_a_run_is_served_as_viewer_records(client):
    records = client.get("/api/runs/smoke-5").json()
    kinds = {r["kind"] for r in records}
    assert "ledger" in kinds and "mutation" not in kinds


def test_an_unknown_run_is_a_404(client):
    assert client.get("/api/runs/nope").status_code == 404


@pytest.mark.parametrize("bad", ["..%2Fsmoke-5", "a/b", ".hidden", "x y"])
def test_a_run_id_cannot_leave_the_runs_directory(client, runs, bad):
    # A real transcript sits wherever each id would lead, so only the guard answers 404.
    transcript = (runs / "smoke-5.jsonl").read_text()
    for target in (
        runs.parent / "smoke-5.jsonl",
        runs / "a" / "b.jsonl",
        runs / ".hidden.jsonl",
        runs / "x y.jsonl",
    ):
        target.parent.mkdir(exist_ok=True)
        target.write_text(transcript)
    assert client.get(f"/api/runs/{bad}").status_code == 404
