import json
import pathlib

import pytest

from casus import bundle, engine
from casus.scenario import Scenario
from helpers import FakeEngine

ROOT = pathlib.Path(__file__).parent.parent
SMOKE = ROOT / "scenarios" / "reference"


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


def test_the_bundled_script_is_syntactically_valid(transcript, tmp_path):
    """The browser caught two defects the suite could not see, and the second was
    a plain name collision. Parsing the script costs nothing and would have."""
    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; this guard needs a JS parser")

    html = bundle.bundle(transcript, tmp_path / "demo.html").read_text()
    blocks = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert blocks, "the bundle carries no script block"
    code = max(blocks, key=len)
    js = tmp_path / "bundled.js"
    js.write_text(code)

    result = subprocess.run(
        [node, "--check", str(js)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0 and not result.stderr, result.stderr[:400]


def test_the_bundle_carries_events_not_v1_resolutions(transcript, tmp_path):
    html = bundle.bundle(transcript, tmp_path / "demo.html").read_text()
    assert "event" in bundle.KEPT_KINDS
    assert '"kind":"resolution"' not in html


def test_the_ledger_stays_in_the_transcript_and_out_of_the_bundle(transcript, tmp_path):
    """Mutations are the audit trail, and the heaviest records; no panel reads them."""
    html = bundle.bundle(transcript, tmp_path / "demo.html").read_text()
    assert '"kind":"mutation"' not in html


def test_viewer_records_count_each_turns_mutations_in_one_ledger_record(transcript):
    records = engine.read_records(transcript)
    counted = {}
    for r in records:
        if r["kind"] == "mutation":
            counted[r["turn"]] = counted.get(r["turn"], 0) + 1
    kept = bundle.viewer_records(records)
    ledgers = {r["turn"]: r["mutations"] for r in kept if r["kind"] == "ledger"}
    assert ledgers == counted
    assert not any(r["kind"] in ("mutation", "declaration") for r in kept)


def test_a_ledger_record_sits_before_the_state_that_closes_its_turn(transcript):
    kept = bundle.viewer_records(engine.read_records(transcript))
    for i, r in enumerate(kept):
        if r["kind"] == "ledger":
            following = next(x for x in kept[i + 1 :] if x["kind"] == "state")
            assert following["turn"] == r["turn"] + 1


def test_an_error_record_reaches_the_viewer():
    records = [
        {"kind": "scenario", "turn": 0, "name": "x", "scenario": {}},
        {"kind": "error", "turn": 1, "error": "rule raised"},
    ]
    assert bundle.viewer_records(records)[-1]["kind"] == "error"


def test_the_bundle_inlines_every_viewer_script_in_order(transcript, tmp_path):
    html = bundle.bundle(transcript, tmp_path / "demo.html").read_text()
    positions = [html.index(f"/* ui/js/{name} */") for name in bundle.SCRIPTS]
    assert positions == sorted(positions)
    assert bundle.SCRIPTS == ("i18n.js", "records.js", "map.js", "card.js", "viewer.js")


def test_the_bundle_boots_the_viewer_in_recorded_mode(transcript, tmp_path):
    html = bundle.bundle(transcript, tmp_path / "demo.html").read_text()
    assert 'Casus.viewer.mount(' in html and '"recorded"' in html


def test_no_script_or_style_in_the_bundle_names_a_web_font(transcript, tmp_path):
    html = bundle.bundle(transcript, tmp_path / "demo.html").read_text()
    assert "fonts.googleapis" not in html and "@import" not in html
