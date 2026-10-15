"""Lint: Cypher must stay static and parameterised (no f-strings, no .format on queries)."""

from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "pedigree"
CYPHER_KEYWORDS = ("MATCH", "CREATE", "MERGE", "UNWIND", "SET ", "DELETE", "RETURN", "CALL ")


def _dynamic_literals(tree: ast.AST):
    """Yield (lineno, literal) for every INTERPOLATED string.

    Covers f-strings, .format()/.replace()/.join() on literal receivers, string
    concatenation and %-formatting (QA finding 2026-10-15: the first version evaded
    concatenation, %, join and replace).
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
            yield node.lineno, text
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            recv = node.func.value
            if (
                isinstance(recv, ast.Constant)
                and isinstance(recv.value, str)
                and node.func.attr in ("format", "replace", "join")
            ):
                yield node.lineno, recv.value
                if node.func.attr == "join":  # risky strings live in the argument list
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                            yield sub.lineno, sub.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
            for side in (node.left, node.right):
                for sub in ast.walk(side):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        yield sub.lineno, sub.value


def test_no_interpolated_cypher_anywhere():
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, text in _dynamic_literals(tree):
            upper = text.upper()
            if any(kw in upper for kw in CYPHER_KEYWORDS):
                offenders.append(f"{path.relative_to(SRC)}:{lineno}: {text[:70]!r}")
    assert not offenders, "interpolated Cypher found (use db/queries.py constants):\n" + "\n".join(offenders)


def test_queries_module_uses_only_the_label_guard():
    text = (SRC / "db" / "queries.py").read_text(encoding="utf-8")
    assert "f\"" not in text and "f'" not in text
    # exactly one .format() call, inside q_create_with_parents, fed by the _label() allow-list
    assert text.count(".format(") == 1
    assert "def _label(" in text and "def q_create_with_parents(" in text


def test_query_constants_have_no_string_interpolation():
    """Braces in Cypher maps/patterns ({id:i}) are fine; non-map {name} placeholders are not."""
    import re

    import pedigree.db.queries as Q

    for name in dir(Q):
        value = getattr(Q, name)
        if not (name.startswith("Q_") and isinstance(value, str) and value):
            continue
        assert not re.search(r"\$\{", value), f"{name} contains JS-style interpolation"
        for inner in re.findall(r"\{([^{}]*)\}", value):
            assert not inner or ":" in inner, (
                f"{name} contains a non-map placeholder {{{inner}}}; "
                "use Cypher parameters ($x), not string interpolation"
            )
