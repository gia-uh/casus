"""The command line, run the way a person runs it."""

from scenariopaths import SCENARIOS

from casus import cli


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
