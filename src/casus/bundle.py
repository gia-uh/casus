"""Transcript plus map into one self-contained HTML file.

The output loads nothing from the network. That is the point: the demo runs from a
laptop with no connection, off a USB stick, in a room whose wifi cannot be
trusted, and it cannot fail for a reason unrelated to what it is showing.
"""

from __future__ import annotations

import json
import pathlib

TEMPLATE = pathlib.Path(__file__).parent.parent.parent / "ui" / "replay.html"
WORLDMAP = pathlib.Path(__file__).parent.parent.parent / "ui" / "worldmap.json"

DATA_TOKEN = "__CASUS_DATA__"
MAP_TOKEN = "__CASUS_WORLDMAP__"

#: Record kinds the replayer reads. The raw `declaration` records are dropped:
#: they are the replay payload, they stay in the transcript for audit, and no
#: panel displays them. The `action` records already carry the rationale.
KEPT_KINDS = frozenset(
    {"scenario", "state", "action", "resolution", "narrative", "prompt", "end"}
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
    kept = [r for r in records if r["kind"] in KEPT_KINDS]
    if not any(r["kind"] == "state" for r in kept):
        raise BundleError(f"{transcript} has no state records to replay")

    html = (template or TEMPLATE).read_text()
    map_json = (worldmap or WORLDMAP).read_text()

    # A closing script tag inside inlined JSON would end the block early and
    # leave the rest of the payload rendering as page text.
    payload = _escape(json.dumps(kept, ensure_ascii=False, separators=(",", ":")))
    html = html.replace(DATA_TOKEN, payload).replace(MAP_TOKEN, _escape(map_json))

    out_path = pathlib.Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _read(path: pathlib.Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _escape(text: str) -> str:
    return text.replace("</script", "<\\/script").replace("<!--", "<\\!--")
