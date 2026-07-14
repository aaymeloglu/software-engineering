"""Static check: flag SQL built by string interpolation of untrusted values.

The naive "f-string contains SELECT => injection risk" regex generates false
positives on patterns like

    for table in ("users", "posts", "reactions"):
        conn.execute(text(f"DELETE FROM {table}"))

where every interpolation is a compile-time string literal and no user input
can reach the SQL text. This module walks the AST, tracks which names are
bound exclusively to string literals (or iterated over literal-string
iterables), and only flags interpolations whose values aren't provably safe.

Public entry point: `find_unsafe_sql_strings(source, filename)` → list of
`Offender` records. Reusable across assignments.
"""
from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass


SQL_VERB_RE = re.compile(
    r"\b(SELECT|INSERT\s+INTO|UPDATE\b|DELETE\s+FROM|CREATE\s+TABLE|"
    r"DROP\s+TABLE|ALTER\s+TABLE|CREATE\s+INDEX|DROP\s+INDEX|"
    r"PRAGMA\s+table_info)\b",
    re.IGNORECASE,
)


@dataclass
class Offender:
    filename: str
    lineno: int
    kind: str       # "fstring" | "format" | "percent"
    snippet: str    # short preview of the offending expression
    reason: str     # why we flagged it — which interpolation isn't literal-safe


def _is_string_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _collect_literal_safe_names(tree: ast.Module) -> set[str]:
    """Names that are provably bound only to string literals or to iteration
    over a literal-string iterable. Tracked at module scope; shadowing inside
    nested scopes is conservatively ignored (a nested reassignment to a
    non-literal would NOT invalidate the module-level binding, but the
    converse is true too, so we'd under-flag in rare cases — acceptable).

    Handles:
      - Plain assignment: x = "literal"
      - Annotated assignment: x: str = "literal"
      - Simple for-loop: for x in ("a", "b"): ...
      - Tuple-unpacking for-loop: for a, b in [("x","y"), ("z","w")]: ...
      - Comprehensions: (... for x in (...) ...) and sibling List/Set/Dict comps.
    """
    assignments: dict[str, list[ast.AST]] = defaultdict(list)
    # (name, iter_node, tuple_index_or_None) for every for-target binding
    for_bindings: list[tuple[str, ast.AST, int | None]] = []

    def _record_for_target(target: ast.AST, iter_node: ast.AST) -> None:
        if isinstance(target, ast.Name):
            for_bindings.append((target.id, iter_node, None))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for idx, elt in enumerate(target.elts):
                if isinstance(elt, ast.Name):
                    for_bindings.append((elt.id, iter_node, idx))

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id].append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                assignments[node.target.id].append(node.value)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            _record_for_target(node.target, node.iter)
        elif isinstance(node, ast.comprehension):
            _record_for_target(node.target, node.iter)

    def _iterable_of_string_literals(expr: ast.AST, seen: set[int] | None = None) -> bool:
        """True if `expr` evaluates to an iterable whose every element is a
        string literal (possibly by recursion through Name bindings)."""
        seen = seen or set()
        if id(expr) in seen:
            return False
        seen.add(id(expr))
        if isinstance(expr, (ast.Tuple, ast.List, ast.Set)):
            return bool(expr.elts) and all(_is_string_constant(e) for e in expr.elts)
        if isinstance(expr, ast.Name):
            rhss = assignments.get(expr.id)
            if not rhss:
                return False
            return all(_iterable_of_string_literals(rhs, seen) for rhs in rhss)
        return False

    def _iterable_of_tuples_of_string_literals(
        expr: ast.AST, pos: int, seen: set[int] | None = None
    ) -> bool:
        """True if `expr` evaluates to an iterable of tuples/lists, every one
        of which has a string literal at index `pos`."""
        seen = seen or set()
        if id(expr) in seen:
            return False
        seen.add(id(expr))
        if isinstance(expr, (ast.Tuple, ast.List, ast.Set)):
            for elt in expr.elts:
                if not isinstance(elt, (ast.Tuple, ast.List)):
                    return False
                if pos >= len(elt.elts) or not _is_string_constant(elt.elts[pos]):
                    return False
            return bool(expr.elts)
        if isinstance(expr, ast.Name):
            rhss = assignments.get(expr.id)
            if not rhss:
                return False
            return all(
                _iterable_of_tuples_of_string_literals(rhs, pos, seen) for rhs in rhss
            )
        return False

    safe: set[str] = set()
    for name, rhss in assignments.items():
        if rhss and all(_is_string_constant(rhs) for rhs in rhss):
            safe.add(name)
    for name, iter_node, tuple_pos in for_bindings:
        if tuple_pos is None:
            if _iterable_of_string_literals(iter_node):
                safe.add(name)
        else:
            if _iterable_of_tuples_of_string_literals(iter_node, tuple_pos):
                safe.add(name)
    return safe


def _fstring_template_and_safety(
    node: ast.JoinedStr, safe_names: set[str]
) -> tuple[str, list[str]]:
    """Return (reconstructed template with {} placeholders, list of unsafe
    interpolation descriptions). If the list is empty, every interpolation is
    literal-safe.
    """
    template_parts: list[str] = []
    unsafe: list[str] = []
    for v in node.values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            template_parts.append(v.value)
        elif isinstance(v, ast.FormattedValue):
            template_parts.append("{}")
            expr = v.value
            if isinstance(expr, ast.Name) and expr.id in safe_names:
                continue
            # Anything else — attribute access, call, subscript, binop, or a
            # Name not in safe_names — is treated as potentially unsafe.
            unsafe.append(ast.unparse(expr) if hasattr(ast, "unparse") else "<expr>")
    return "".join(template_parts), unsafe


def find_unsafe_sql_strings(source: str, filename: str = "<source>") -> list[Offender]:
    """Parse `source`, return every f-string / .format() / %-format string
    that (a) contains a SQL verb in its template and (b) has at least one
    interpolation that isn't provably a literal string.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    safe_names = _collect_literal_safe_names(tree)
    offenders: list[Offender] = []

    for node in ast.walk(tree):
        # --- f-strings
        if isinstance(node, ast.JoinedStr):
            template, unsafe = _fstring_template_and_safety(node, safe_names)
            if unsafe and SQL_VERB_RE.search(template):
                snippet = template[:70]
                reason = f"interpolates non-literal: {', '.join(unsafe[:3])}"
                offenders.append(Offender(filename, node.lineno, "fstring", snippet, reason))
            continue

        # --- "...".format(...)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format"
            and isinstance(node.func.value, ast.Constant)
            and isinstance(node.func.value.value, str)
        ):
            tmpl = node.func.value.value
            if SQL_VERB_RE.search(tmpl):
                unsafe = []
                for arg in list(node.args) + [kw.value for kw in node.keywords]:
                    if isinstance(arg, ast.Name) and arg.id in safe_names:
                        continue
                    if _is_string_constant(arg):
                        continue
                    unsafe.append(ast.unparse(arg) if hasattr(ast, "unparse") else "<arg>")
                if unsafe:
                    offenders.append(Offender(
                        filename, node.lineno, "format", tmpl[:70],
                        f".format() with non-literal: {', '.join(unsafe[:3])}",
                    ))
            continue

        # --- "SELECT ..." % (args,)
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Mod)
            and isinstance(node.left, ast.Constant)
            and isinstance(node.left.value, str)
        ):
            tmpl = node.left.value
            if SQL_VERB_RE.search(tmpl):
                unsafe = []
                rhs = node.right
                args: list[ast.AST]
                if isinstance(rhs, (ast.Tuple, ast.List)):
                    args = list(rhs.elts)
                else:
                    args = [rhs]
                for arg in args:
                    if isinstance(arg, ast.Name) and arg.id in safe_names:
                        continue
                    if _is_string_constant(arg):
                        continue
                    unsafe.append(ast.unparse(arg) if hasattr(ast, "unparse") else "<arg>")
                if unsafe:
                    offenders.append(Offender(
                        filename, node.lineno, "percent", tmpl[:70],
                        f"%-format with non-literal: {', '.join(unsafe[:3])}",
                    ))
    return offenders
