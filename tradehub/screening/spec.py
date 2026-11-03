"""Spec validation: JSON Schema first, then catalog checks that NAME the bad
function or param (an AI emitting specs needs errors it can act on)."""

from __future__ import annotations

import json
from pathlib import Path

from .functions import REGISTRY
from .catalog import OPS

_SCHEMA_PATH = Path(__file__).parent / "query_spec.schema.json"
_OPS = {o["op"] for o in OPS}
_TYPEMAP = {"int": int, "float": (int, float), "str": str}


class SpecError(ValueError):
    pass


DERIVED_KIND = {"kind": "field", "returns": "float", "params": {}}


def derived_names(spec: dict) -> set[str]:
    return {d["name"] for d in spec.get("derived") or []}


def _check_fn_call(call: dict, where: str, want_kind: str, derived: set[str] | None = None) -> None:
    name = call.get("fn")
    if derived and name in derived:
        if call.get("params"):
            raise SpecError(f"{where}: derived field '{name}' takes no params")
        return
    entry = REGISTRY.get(name)
    if entry is None:
        raise SpecError(f"{where}: unknown function '{name}' "
                        f"(see catalog.json for the {len(REGISTRY)} registered names)")
    if entry["kind"] != want_kind:
        raise SpecError(f"{where}: function '{name}' is kind '{entry['kind']}', "
                        f"not usable as a {want_kind} here")
    params = call.get("params") or {}
    declared = entry["params"]
    for p in params:
        if p not in declared:
            raise SpecError(f"{where}: function '{name}' has no param '{p}' "
                            f"(declared: {', '.join(declared) or 'none'})")
    for p, v in params.items():
        t = declared[p]["type"]
        if t == "float" and isinstance(v, bool):
            raise SpecError(f"{where}: param '{p}' of '{name}' must be a number")
        if not isinstance(v, _TYPEMAP[t]) or (t == "int" and isinstance(v, bool)):
            raise SpecError(f"{where}: param '{p}' of '{name}' must be {t}, "
                            f"got {type(v).__name__}")


def validate_spec(spec: dict) -> dict:
    """Returns the spec unchanged if valid; raises SpecError otherwise."""
    import jsonschema

    schema = json.loads(_SCHEMA_PATH.read_text())
    try:
        jsonschema.validate(spec, schema)
    except jsonschema.ValidationError as e:
        raise SpecError(f"schema: {e.message} (at {'.'.join(map(str, e.path)) or 'root'})") from e

    derived = _validate_derived(spec)
    for i, f in enumerate(spec.get("filters") or []):
        where = f"filters[{i}]"
        _check_fn_call(f, where, "field", derived)
        if f["op"] not in _OPS:
            raise SpecError(f"{where}: unknown op '{f['op']}'")
        entry = REGISTRY.get(f["fn"]) or DERIVED_KIND
        if entry["returns"] == "str" and f["op"] not in ("eq", "ne", "in"):
            raise SpecError(f"{where}: function '{f['fn']}' returns strings; "
                            f"op '{f['op']}' is numeric-only (use eq/ne/in)")
        if f["op"] in ("pct_gte", "pct_lte") and entry["returns"] == "str":
            raise SpecError(f"{where}: percentile ops need a numeric function")
        if f["op"] == "between" and not (isinstance(f["value"], list) and len(f["value"]) == 2):
            raise SpecError(f"{where}: op 'between' needs value = [lo, hi]")
        if f["op"] == "in" and not isinstance(f["value"], list):
            raise SpecError(f"{where}: op 'in' needs value = [ ... ]")
    for i, s in enumerate(spec.get("score") or []):
        _check_fn_call(s, f"score[{i}]", "field", derived)
        if (REGISTRY.get(s["fn"]) or DERIVED_KIND)["returns"] == "str":
            raise SpecError(f"score[{i}]: cannot score on string function '{s['fn']}'")
    for i, c in enumerate(spec.get("context") or []):
        _check_fn_call(c, f"context[{i}]", "context")
    return spec


def _validate_derived(spec: dict) -> set[str]:
    """Derived ratios (Kevin, 2026-11-02): a named expression over catalog field
    names. The expression grammar is arithmetic only -- + - * /, parentheses,
    numeric literals, and field names -- validated on the AST, never eval'd
    blind. Every referenced name must be a registered numeric field function."""
    import ast

    names: set[str] = set()
    for i, d in enumerate(spec.get("derived") or []):
        where = f"derived[{i}]"
        name = d["name"]
        if name in REGISTRY:
            raise SpecError(f"{where}: derived name '{name}' collides with a catalog function")
        if name in names:
            raise SpecError(f"{where}: derived name '{name}' is defined twice")
        names.add(name)
        try:
            tree = ast.parse(d["expr"], mode="eval")
        except SyntaxError as e:
            raise SpecError(f"{where}: expression does not parse: {e.msg}") from e
        for node in ast.walk(tree):
            if isinstance(node, ast.Expression):
                continue
            if isinstance(node, ast.BinOp):
                if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
                    raise SpecError(f"{where}: only + - * / are allowed in a derived expression")
                continue
            if isinstance(node, ast.UnaryOp):
                if not isinstance(node.op, (ast.UAdd, ast.USub)):
                    raise SpecError(f"{where}: only unary +/- are allowed in a derived expression")
                continue
            if isinstance(node, ast.Name):
                entry = REGISTRY.get(node.id)
                if entry is None:
                    raise SpecError(f"{where}: unknown field '{node.id}' in the expression "
                                    f"(derived fields compose catalog fields, not other derived fields)")
                if entry["kind"] != "field" or entry["returns"] == "str":
                    raise SpecError(f"{where}: field '{node.id}' is not a numeric field function")
                continue
            if isinstance(node, ast.Constant):
                if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                    raise SpecError(f"{where}: only numeric literals are allowed in a derived expression")
                continue
            if isinstance(node, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.UAdd, ast.USub, ast.Load)):
                continue
            raise SpecError(f"{where}: expression element {type(node).__name__} is not allowed "
                            f"(arithmetic over catalog fields only)")
    return names
