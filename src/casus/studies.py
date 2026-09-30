"""What is on disk under runs/: which transcripts exist and how far each got.

A run's id is its file stem. Reading a run's header costs one line; counting
its turns costs a pass over the file, which is fine for a class's worth of runs.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Literal

Status = Literal["complete", "failed", "incomplete"]


@dataclasses.dataclass(frozen=True)
class RunInfo:
    id: str
    path: pathlib.Path
    scenario: str
    seed: int
    turns_planned: int
    turns_done: int
    status: Status

    def to_json(self) -> dict:
        return {**dataclasses.asdict(self), "path": str(self.path)}


class NotATranscript(ValueError):
    """A file under runs/ that does not read as a transcript."""


def read_transcript(path: pathlib.Path) -> tuple[list[dict], bool]:
    """Every record in `path`, and whether its last line was torn.

    A half-written last line, even one cut inside a UTF-8 character, is the end
    of the file: a run killed mid-write leaves one. An undecodable line with
    another after it, or a line that is not a JSON object, is not a transcript.
    """
    records: list[dict] = []
    torn = False
    with path.open("rb") as fh:
        for line in fh:
            if not line.strip():
                continue
            if torn:
                raise NotATranscript(f"{path}: an undecodable line is not the last")
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                torn = True
                continue
            if not isinstance(record, dict):
                raise NotATranscript(f"{path}: a line is not a JSON object")
            records.append(record)
    return records, torn


def _scan(path: pathlib.Path) -> RunInfo | None:
    try:
        records, torn = read_transcript(path)
    except (OSError, NotATranscript):
        return None
    header, states, failed, ended = None, 0, False, False
    for record in records:
        kind = record.get("kind")
        if header is None:
            if kind != "scenario":
                return None
            header = record
        elif kind == "state":
            states += 1
        elif kind == "error":
            failed = True
        elif kind == "end":
            ended = True
    if header is None:
        return None
    status: Status = "failed" if failed else "complete" if ended and not torn else "incomplete"
    try:
        seed, turns_planned = int(header.get("seed", 0)), int(header.get("turns", 0))
    except (TypeError, ValueError, OverflowError):
        return None
    return RunInfo(
        id=path.stem,
        path=path,
        scenario=str(header.get("name", "")),
        seed=seed,
        turns_planned=turns_planned,
        turns_done=max(states - 1, 0),
        status=status,
    )


def list_runs(runs_dir: pathlib.Path) -> list[RunInfo]:
    """Every readable transcript directly under `runs_dir`, sorted by id."""
    if not runs_dir.is_dir():
        return []
    found = (_scan(p) for p in sorted(runs_dir.glob("*.jsonl")))
    return [info for info in found if info is not None]
