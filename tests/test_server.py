import pathlib
import shutil

import pytest
import yaml
from fastapi.testclient import TestClient

from casus import bundle, engine
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


def test_a_run_cut_mid_line_is_served_without_its_torn_last_line(client, runs):
    path = runs / "smoke-5.jsonl"
    whole = bundle.viewer_records(engine.read_records(path))
    path.write_text(path.read_text() + '{"kind":"sta')
    response = client.get("/api/runs/smoke-5")
    assert response.status_code == 200
    assert response.json() == whole


def test_a_run_that_is_not_a_transcript_is_a_404(client, runs):
    lines = (runs / "smoke-5.jsonl").read_text().splitlines()
    (runs / "mangled.jsonl").write_text("\n".join([lines[0], "{", *lines[1:]]) + "\n")
    assert client.get("/api/runs/mangled").status_code == 404


def test_an_unknown_run_is_a_404(client):
    assert client.get("/api/runs/nope").status_code == 404


@pytest.mark.parametrize("bad", ["..\\smoke-5", ".hidden", "x y"])
def test_a_run_id_cannot_leave_the_runs_directory(client, runs, bad):
    # A real transcript sits wherever each id could lead, so only the guard
    # answers 404. `..\smoke-5` routes as one segment: on Windows it climbs out
    # of runs/, on Linux it names a file with a backslash in it. An id with a
    # slash never reaches the guard, because routing rejects it first.
    transcript = (runs / "smoke-5.jsonl").read_text()
    for target in (
        runs.parent / "smoke-5.jsonl",
        runs / "..\\smoke-5.jsonl",
        runs / ".hidden.jsonl",
        runs / "x y.jsonl",
    ):
        target.write_text(transcript)
    assert client.get(f"/api/runs/{bad}").status_code == 404


def test_a_broken_scenario_gets_a_card_and_does_not_blank_the_list(tmp_path, runs):
    scenarios = tmp_path / "scenarios"
    shutil.copytree(SCENARIOS / "smoke", scenarios / "smoke")
    shutil.copytree(SCENARIOS / "smoke", scenarios / "bad-rules")
    (scenarios / "bad-rules" / "rules.py").write_text("import os\n")
    (scenarios / "bad-yaml").mkdir()
    (scenarios / "bad-yaml" / "scenario.yaml").write_text("name: [unclosed\n")
    client = TestClient(create_app(scenarios_dir=scenarios, runs_dir=runs))

    response = client.get("/api/scenarios")

    assert response.status_code == 200
    by_dir = {s["dir"]: s for s in response.json()}
    assert by_dir.keys() == {"smoke", "bad-rules", "bad-yaml"}
    for broken in ("bad-rules", "bad-yaml"):
        assert by_dir[broken]["valid"] is False and by_dir[broken]["findings"]
    assert by_dir["bad-yaml"]["name"] == "bad-yaml"
    assert by_dir["bad-yaml"]["actors"] is None
    assert by_dir["smoke"]["valid"] is True


@pytest.mark.parametrize("breakage", ["directory", "dangling symlink"])
def test_a_scenario_with_no_regular_files_still_gets_a_card(tmp_path, runs, breakage):
    scenarios = tmp_path / "scenarios"
    shutil.copytree(SCENARIOS / "smoke", scenarios / "smoke")
    broken = scenarios / "broken" / "scenario.yaml"
    broken.parent.mkdir()
    if breakage == "directory":
        broken.mkdir()
    else:
        broken.symlink_to(tmp_path / "nowhere.yaml")
    client = TestClient(create_app(scenarios_dir=scenarios, runs_dir=runs))
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    by_dir = {s["dir"]: s for s in response.json()}
    assert by_dir["broken"]["valid"] is False and by_dir["smoke"]["valid"] is True


@pytest.mark.parametrize(
    ("turns", "shown"), [(4, 4), ("<img src=x onerror=window.PWNED=1>", None), (True, None)]
)
def test_a_card_shows_turns_only_when_they_are_a_whole_number(tmp_path, runs, turns, shown):
    scenarios = tmp_path / "scenarios"
    shutil.copytree(SCENARIOS / "smoke", scenarios / "smoke")
    manifest = scenarios / "smoke" / "scenario.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    manifest.write_text(yaml.safe_dump({**data, "turns": turns}), encoding="utf-8")
    client = TestClient(create_app(scenarios_dir=scenarios, runs_dir=runs))
    [card] = client.get("/api/scenarios").json()
    assert card["turns"] == shown


@pytest.mark.parametrize("stem", ["my run", "it's", "evil\n"])
def test_a_run_the_endpoint_refuses_is_not_listed(client, runs, stem):
    shutil.copy(runs / "smoke-5.jsonl", runs / f"{stem}.jsonl")
    assert [r["id"] for r in client.get("/api/runs").json()] == ["smoke-5"]


def test_a_symlink_out_of_the_runs_directory_is_neither_listed_nor_served(client, runs):
    outside = runs.parent / "outside.jsonl"
    shutil.copy(runs / "smoke-5.jsonl", outside)
    (runs / "evil.jsonl").symlink_to(outside)
    assert [r["id"] for r in client.get("/api/runs").json()] == ["smoke-5"]
    assert client.get("/api/runs/evil").status_code == 404
