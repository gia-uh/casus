"""Every text read and write in the app's modules names its encoding.

Without one, Python uses the locale's, which is cp1252 on a Windows laptop, and
the UI scripts carry characters cp1252 cannot decode, so `casus bundle` and
`casus serve` would crash there. CI runs on UTF-8 Linux and never sees it, so
this reads the source instead.
"""

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).parent.parent / "src" / "casus"
MODULES = [SRC / "bundle.py", SRC / "display.py", SRC / "studies.py", *SRC.glob("server/*.py")]
TEXT_CALLS = {"read_text", "write_text", "open"}


def _unencoded(path: pathlib.Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name not in TEXT_CALLS or any(k.arg == "encoding" for k in node.keywords):
            continue
        modes = [a.value for a in node.args if isinstance(a, ast.Constant)]
        modes += [k.value.value for k in node.keywords if k.arg == "mode"]
        if any(isinstance(m, str) and "b" in m for m in modes):
            continue
        found.append(f"{path.name}:{node.lineno} {name}()")
    return found


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_text_io_names_its_encoding(path):
    assert _unencoded(path) == []


def test_the_check_sees_a_call_without_an_encoding(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text('p.read_text()\nopen("x")\np.open("rb")\np.write_text(s, encoding="utf-8")\n')
    assert _unencoded(bad) == ["bad.py:1 read_text()", "bad.py:2 open()"]
