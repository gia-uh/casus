"""Validation of a scenario's rules: static (the source), dynamic (a dry turn),
and invariants (many turns). Each returns findings rather than raising, so a
scenario author sees every problem at once."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Finding:
    code: str
    message: str
    file: str = ""
    line: int = 0

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}: " if self.file else ""
        return f"{where}{self.code}: {self.message}"
