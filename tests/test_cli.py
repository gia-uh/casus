"""The command line, run the way a person runs it."""

import json

import yaml
from scenariopaths import SCENARIOS

from casus import cli
from casus.geo.regions import region_digest
from helpers import (
    CUBA_BLOCKS,
    SMOKE_REGION_BLOCKS,
    SMOKE_REGION_GRAPH,
    smoke_with_regions,
    write_regions,
)


def test_validate_passes_a_clean_scenario(capsys):
    assert cli.main(["validate", str(SCENARIOS / "smoke")]) == 0
    assert "no findings" in capsys.readouterr().out


def test_validate_reports_findings_and_fails(tmp_path, capsys):
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / "scenario.yaml").write_text(
        (SCENARIOS / "smoke" / "scenario.yaml").read_text()
    )
    (directory / "rules.py").write_text("import os\n")
    assert cli.main(["validate", str(directory)]) == 1
    assert "forbidden-import" in capsys.readouterr().out


def test_serve_starts_uvicorn_on_loopback(monkeypatch):
    calls = {}

    def fake_run(app, host, port, log_level):
        calls.update(host=host, port=port)

    monkeypatch.setattr("uvicorn.run", fake_run)
    assert cli.main(["serve", "--no-open", "--port", "8765"]) == 0
    assert calls == {"host": "127.0.0.1", "port": 8765}


def test_regions_writes_regions_json_from_the_packaged_map(tmp_path, capsys):
    directory = smoke_with_regions(tmp_path, CUBA_BLOCKS)
    assert cli.main(["regions", str(directory)]) == 0
    doc = json.loads((directory / "regions.json").read_text())
    places = yaml.safe_load((directory / "scenario.yaml").read_text())["places"]
    assert doc["digest"] == region_digest(places)
    assert doc["adjacency"]["b-home"] == ["border", "r-home"]
    assert set(doc["places"]) == set(CUBA_BLOCKS)
    assert "wrote" in capsys.readouterr().out


def test_regions_with_findings_writes_nothing_and_fails(tmp_path, capsys):
    blocks = {**CUBA_BLOCKS, "border": {"provinces": ["CU-02"]}}
    directory = smoke_with_regions(tmp_path, blocks)
    assert cli.main(["regions", str(directory)]) == 1
    out = capsys.readouterr().out
    assert "unknown-province" in out and "CU-03 (Ciudad de la Habana)" in out
    assert not (directory / "regions.json").exists()


def test_regions_on_a_scenario_without_region_blocks_says_so(capsys):
    assert cli.main(["regions", str(SCENARIOS / "smoke")]) == 2
    assert "no region blocks" in capsys.readouterr().err


def test_validate_prints_an_adjacency_warning_without_failing(tmp_path, capsys):
    def listed(data):
        data["places"]["r-home"]["adjacency"] = ["border", "b-home"]

    directory = smoke_with_regions(
        tmp_path, SMOKE_REGION_BLOCKS, keep_lists=("r-home",), change=listed
    )
    write_regions(directory, SMOKE_REGION_GRAPH)
    assert cli.main(["validate", str(directory), "--turns", "2"]) == 0
    out = capsys.readouterr().out
    assert "warning: " in out and "adjacency-differs" in out
