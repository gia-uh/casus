import json
import pathlib

import pytest

from casus import bundle, engine
from casus.scenario import Scenario
from helpers import FakeEngine

ROOT = pathlib.Path(__file__).parent.parent
SMOKE = ROOT / "scenarios" / "smoke.yaml"


def _engines(scenario, reply=None):
    return {a: FakeEngine(reply) for a in scenario.actors}


@pytest.fixture
def transcript(tmp_path) -> pathlib.Path:
    out = tmp_path / "run.jsonl"
    scenario = Scenario.load(SMOKE)
    engine.run(scenario, seed=1, out=out, engines=_engines(scenario), turns=2)
    return out


def test_bundled_html_loads_nothing_from_the_network(transcript, tmp_path):
    out = bundle.bundle(transcript, tmp_path / "demo.html")
    html = out.read_text()
    assert "<script src=" not in html
    assert "<link" not in html
    assert "@import" not in html


def test_the_bundle_carries_the_run_and_the_map(transcript, tmp_path):
    html = bundle.bundle(transcript, tmp_path / "demo.html").read_text()
    assert bundle.DATA_TOKEN not in html, "the data placeholder was never filled"
    assert bundle.MAP_TOKEN not in html, "the map placeholder was never filled"
    assert '"kind":"state"' in html
    assert '"countries"' in html


def test_the_embedded_json_parses_back_to_the_records(transcript, tmp_path):
    """A bundle whose JSON does not parse renders as a blank page, which is the
    failure mode a green test would otherwise hide."""
    html = bundle.bundle(transcript, tmp_path / "demo.html").read_text()
    start = html.index('<script id="casus-data" type="application/json">') + len(
        '<script id="casus-data" type="application/json">'
    )
    end = html.index("</script>", start)
    records = json.loads(html[start:end].replace("<\\/script", "</script"))
    assert [r["kind"] for r in records if r["kind"] == "state"]
    assert any(r["kind"] == "prompt" for r in records)


def test_raw_completions_are_left_out_to_keep_the_file_small(transcript, tmp_path):
    html = bundle.bundle(transcript, tmp_path / "demo.html").read_text()
    assert '"kind":"declaration"' not in html
    assert "declaration" not in bundle.KEPT_KINDS


def test_the_prompt_the_model_saw_is_in_the_bundle(transcript, tmp_path):
    """The prompt drawer is the single most valuable panel for a non-technical
    audience, so its content has to survive bundling."""
    html = bundle.bundle(transcript, tmp_path / "demo.html").read_text()
    assert "YOUR STANDING ORDERS" in html


def test_a_transcript_with_no_states_is_refused(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text(json.dumps({"kind": "end", "turn": 0}) + "\n")
    with pytest.raises(bundle.BundleError, match="no state records"):
        bundle.bundle(empty, tmp_path / "x.html")


def test_a_closing_script_tag_in_the_data_cannot_end_the_block_early(tmp_path):
    """A rationale containing '</script>' would otherwise truncate the payload
    and render the rest of the run as page text."""
    out = tmp_path / "run.jsonl"
    scenario = Scenario.load(SMOKE)
    engine.run(scenario, seed=1, out=out, engines=_engines(scenario, _HOSTILE), turns=1)
    html = bundle.bundle(out, tmp_path / "demo.html").read_text()
    body = html.split('<script id="casus-data" type="application/json">')[1]
    payload = body.split("</script>")[0]
    assert json.loads(payload.replace("<\\/script", "</script"))


#: A rationale carrying a closing script tag. Without escaping this truncates the
#: inlined payload and renders the rest of the run as page text.
_HOSTILE = {
    "actions": [{"type": "hold"}],
    "rationale": "we will </script><h1>own the page</h1> hold",
    "assessment": "",
}
