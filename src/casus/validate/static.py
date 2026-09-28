"""What a rules file may not do, found by reading it without running it.

The checks exist to keep the ledger honest and the run reproducible. A rule that
assigns to state directly changes a number without leaving a trace; one that
imports `random` or `time`, or orders by `id()`, stops the same seed giving the
same run; one that writes module state carries something from one turn to the
next outside the world.

This is not a sandbox. It stops the obvious ways out of the proxy, and a rules
file still runs in the engine's process.
"""

from __future__ import annotations

import ast

from ..ruleset import PHASES
from . import Finding

ALLOWED_IMPORTS = frozenset({"casus.ruleset", "math", "__future__"})

FORBIDDEN_CALLS = frozenset(
    {
        "open", "exec", "eval", "compile", "__import__", "input", "breakpoint",
        "globals", "locals", "vars", "setattr", "delattr", "getattr", "id", "hash",
    }
)  # fmt: skip

MUTATING_METHODS = frozenset(
    {"append", "extend", "insert", "remove", "pop", "clear", "update", "add", "discard",
     "setdefault", "popitem", "sort", "reverse"}
)  # fmt: skip

IMPORT_ADVICE = {
    "random": "randomness enters through s.rng, which the engine seeds",
    "time": "a rule cannot depend on the clock; the same seed must give the same run",
    "datetime": "a rule cannot depend on the clock; the same seed must give the same run",
}


def check_source(source: str, filename: str = "rules.py") -> list[Finding]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [Finding("syntax-error", str(exc.msg), filename, exc.lineno or 0)]
    checker = _Checker(filename, _module_names(tree))
    checker.visit(tree)
    return sorted(checker.findings, key=lambda f: (f.line, f.code))


def _module_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets = [node.target]
        for target in targets:
            names |= {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
    return names


def _decorator(node: ast.expr) -> tuple[str, ast.Call | None]:
    """The decorator's name, and its call if it was called with arguments."""
    call = node if isinstance(node, ast.Call) else None
    target = call.func if call else node
    if isinstance(target, ast.Name):
        return target.id, call
    if isinstance(target, ast.Attribute):
        return target.attr, call
    return "", call


def _keyword(call: ast.Call | None, name: str) -> ast.expr | None:
    if call is None:
        return None
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


class _Checker(ast.NodeVisitor):
    def __init__(self, filename: str, module_names: set[str]):
        self.filename = filename
        self.module_names = module_names
        self.findings: list[Finding] = []
        self._locals: list[set[str]] = []

    def _add(self, code: str, message: str, node: ast.AST) -> None:
        self.findings.append(Finding(code, message, self.filename, getattr(node, "lineno", 0)))

    # --- imports ----------------------------------------------------------

    def _check_module(self, module: str, node: ast.AST) -> None:
        if module in ALLOWED_IMPORTS:
            return
        root = module.split(".")[0]
        advice = IMPORT_ADVICE.get(
            root, f"a rules file may import only {sorted(ALLOWED_IMPORTS)}"
        )
        self._add("forbidden-import", f"import of '{module}': {advice}", node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_module(alias.name, node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._check_module(node.module or "", node)

    # --- functions and decorators -------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_decorators(node)
        assigned = {
            n.id
            for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
        } | {a.arg for a in node.args.args}
        self._locals.append(assigned)
        self.generic_visit(node)
        self._locals.pop()

    def _check_decorators(self, node: ast.FunctionDef) -> None:
        arity = len(node.args.args)
        for decorator in node.decorator_list:
            name, call = _decorator(decorator)
            if name == "rule":
                phase = _keyword(call, "phase")
                if isinstance(phase, ast.Constant) and phase.value not in PHASES:
                    self._add(
                        "unknown-phase",
                        f"rule '{node.name}' names phase {phase.value!r}; "
                        f"the phases are {', '.join(PHASES)}",
                        decorator,
                    )
                wanted = 2 if _keyword(call, "on") is not None else 1
                if arity != wanted:
                    shape = "(s, a)" if wanted == 2 else "(s)"
                    self._add(
                        "bad-signature",
                        f"rule '{node.name}' takes {arity} argument(s); "
                        f"a rule {'with' if wanted == 2 else 'without'} on= takes {shape}",
                        node,
                    )
            elif name in ("offer", "view") and arity != 2:
                self._add(
                    "bad-signature",
                    f"@{name} '{node.name}' takes {arity} argument(s); it takes (s, actor)",
                    node,
                )

    def visit_Global(self, node: ast.Global) -> None:
        self._add(
            "module-state",
            f"'global {', '.join(node.names)}' lets a rule carry state between turns "
            "outside the world; keep it in a resource or an attribute",
            node,
        )

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self._add("module-state", "'nonlocal' carries state outside the world", node)

    # --- assignment -------------------------------------------------------

    def _check_target(self, target: ast.expr, node: ast.AST) -> None:
        if isinstance(target, ast.Attribute):
            self._add(
                "direct-assignment",
                f"assigning to '.{target.attr}' changes state without a ledger entry; "
                "use s.set(ref, value) or s.add(ref, delta)",
                node,
            )
        elif isinstance(target, ast.Subscript) and self._is_module_name(target.value):
            self._add(
                "module-state",
                "writing into a module-level table from a rule carries state between turns",
                node,
            )
        elif isinstance(target, ast.Tuple | ast.List):
            for element in target.elts:
                self._check_target(element, node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._check_target(target, node)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._check_target(node.target, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_target(node.target, node)
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self._check_target(target, node)
        self.generic_visit(node)

    def _is_module_name(self, node: ast.expr) -> bool:
        if not self._locals or not isinstance(node, ast.Name):
            return False
        return node.id in self.module_names and node.id not in self._locals[-1]

    # --- calls and attributes --------------------------------------------

    def visit_Name(self, node: ast.Name) -> None:
        # Anywhere, not only as a call: `sorted(xs, key=id)` orders by memory
        # address just as surely as `id(x)` does.
        if node.id in FORBIDDEN_CALLS and isinstance(node.ctx, ast.Load):
            self._add("forbidden-call", f"'{node.id}' is not available to a rule", node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in MUTATING_METHODS
            and self._is_module_name(func.value)
        ):
            self._add(
                "module-state",
                f"'{func.value.id}.{func.attr}()' changes a module-level value from a rule, "
                "which carries state between turns",
                node,
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__") and node.attr.endswith("__"):
            self._add("forbidden-call", f"dunder access '.{node.attr}' is not available", node)
        elif node.attr.startswith("_"):
            self._add(
                "private-access",
                f"'.{node.attr}' reaches past the rule surface; a change made there "
                "leaves no ledger entry",
                node,
            )
        self.generic_visit(node)
