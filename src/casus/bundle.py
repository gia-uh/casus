"""Transcript plus map into one self-contained HTML file.

The output loads nothing from the network. That is the point: the demo runs from a
laptop with no connection, off a USB stick, in a room whose wifi cannot be
trusted, and it cannot fail for a reason unrelated to what it is showing.
"""

from __future__ import annotations

import json
import pathlib
import re

UI = pathlib.Path(__file__).parent.parent.parent / "ui"
TEMPLATE = UI / "bundle.html"
WORLDMAP = UI / "worldmap.json"
STYLE = UI / "css" / "app.css"

#: The viewer's scripts, in load order. The app loads the same files by URL.
SCRIPTS = ("i18n.js", "records.js", "map.js", "card.js", "viewer.js")

DATA_TOKEN = "__CASUS_DATA__"
MAP_TOKEN = "__CASUS_WORLDMAP__"
STYLE_TOKEN = "__CASUS_STYLE__"
SCRIPTS_TOKEN = "__CASUS_SCRIPTS__"

#: Record kinds the viewer reads. `declaration` records are the replay payload and
#: `mutation` records are the ledger; both stay in the transcript for audit. The
#: `action` records already carry the rationale and the assessment, and the one
#: thing the viewer needs from the ledger, a count per turn, travels as a small
#: `ledger` record written here.
KEPT_KINDS = frozenset(
    {"scenario", "state", "action", "event", "narrative", "prompt", "end", "error"}
)


class BundleError(RuntimeError):
    """The bundle could not be built from what was given."""


def bundle(
    transcript: pathlib.Path | str,
    out: pathlib.Path | str,
    template: pathlib.Path | None = None,
    worldmap: pathlib.Path | None = None,
) -> pathlib.Path:
    """Write a single-file replayer for `transcript`."""
    records = _read(pathlib.Path(transcript))
    kept = viewer_records(records)
    if not any(r["kind"] == "state" for r in kept):
        raise BundleError(f"{transcript} has no state records to replay")

    html = (template or TEMPLATE).read_text(encoding="utf-8")
    map_json = (worldmap or WORLDMAP).read_text(encoding="utf-8")

    # Every template-owned token goes in before the data, so a transcript that
    # happens to contain a token's text cannot inject into the page.
    html = html.replace(STYLE_TOKEN, STYLE.read_text(encoding="utf-8"))
    html = html.replace(SCRIPTS_TOKEN, _escape_script(_scripts()))
    html = html.replace(MAP_TOKEN, _escape_json(map_json))

    # A closing script tag inside inlined JSON would end the block early and
    # run whatever follows it as page markup.
    payload = json.dumps(kept, ensure_ascii=False, separators=(",", ":"))
    html = html.replace(DATA_TOKEN, _escape_json(payload))

    out_path = pathlib.Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def viewer_records(records: list[dict]) -> list[dict]:
    """The records the viewer plays, with each turn's mutations replaced by a
    count placed just before the state that closes that turn."""
    counts: dict[int, int] = {}
    for r in records:
        if r["kind"] == "mutation":
            counts[r["turn"]] = counts.get(r["turn"], 0) + 1
    out: list[dict] = []
    for r in records:
        if r["kind"] == "state" and (r["turn"] - 1) in counts:
            out.append(
                {
                    "kind": "ledger",
                    "turn": r["turn"] - 1,
                    "mutations": counts.pop(r["turn"] - 1),
                }
            )
        if r["kind"] in KEPT_KINDS:
            out.append(r)
    for turn, n in sorted(counts.items()):
        out.append({"kind": "ledger", "turn": turn, "mutations": n})
    return out


def _scripts() -> str:
    return "\n".join(
        f"/* ui/js/{name} */\n" + (UI / "js" / name).read_text(encoding="utf-8")
        for name in SCRIPTS
    )


def _read(path: pathlib.Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _escape_json(text: str) -> str:
    """JSON with no `<` left in it, so no tag in any letter case can open or close.
    In valid JSON a `<` sits only inside a string, where `\\u003c` means the same."""
    return text.replace("<", "\\u003c")


def _escape_script(text: str) -> str:
    """Code with no end tag in it. End-tag names are case-insensitive in HTML."""
    text = re.sub(r"</(script)", r"<\\/\1", text, flags=re.IGNORECASE)
    return text.replace("<!--", "<\\!--")
