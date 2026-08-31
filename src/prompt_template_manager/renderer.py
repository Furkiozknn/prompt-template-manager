"""Turns a Template + variable overrides into a concrete params dict.

Two substitution modes, both deliberate:

- ``${var_name}`` (a param value that IS exactly this, nothing else) ->
  direct substitution of the variable's *typed* value. Use this for
  non-string params (``width: "${img_width}"``) so an integer variable
  stays an integer instead of getting stringified.
- Jinja2 ``{{ var_name }}`` inside a larger string (e.g. a prompt) ->
  ordinary string interpolation, with ``StrictUndefined`` so a typo'd
  variable name fails loudly at render time instead of silently rendering
  as an empty string.

Everything else (ints, floats, bools, and strings with no template syntax
at all) passes through unchanged as a literal.
"""

from __future__ import annotations

import re
from typing import Any

from jinja2 import Environment, StrictUndefined, UndefinedError, meta

from .models import Template, TemplateError

_DIRECT_SIGIL_RE = re.compile(r"^\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}$")

_jinja_env = Environment(undefined=StrictUndefined)


def _coerce(value: Any, var_type: str, var_name: str) -> Any:
    if var_type == "string":
        return str(value)
    if var_type == "integer":
        if isinstance(value, bool):
            raise TemplateError(f"variable {var_name!r}: expected integer, got boolean")
        if isinstance(value, int):
            return value
        try:
            return int(str(value))
        except ValueError:
            raise TemplateError(f"variable {var_name!r}: cannot convert {value!r} to integer")
    if var_type == "float":
        if isinstance(value, bool):
            raise TemplateError(f"variable {var_name!r}: expected float, got boolean")
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value))
        except ValueError:
            raise TemplateError(f"variable {var_name!r}: cannot convert {value!r} to float")
    if var_type == "boolean":
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in ("true", "1", "yes"):
            return True
        if normalized in ("false", "0", "no"):
            return False
        raise TemplateError(f"variable {var_name!r}: cannot convert {value!r} to boolean")
    raise TemplateError(f"variable {var_name!r}: unknown type {var_type!r}")  # pragma: no cover


def resolve_variables(template: Template, overrides: dict[str, Any]) -> dict[str, Any]:
    """Merge CLI/caller-supplied overrides with declared defaults, validate
    required variables are present, coerce every value to its declared
    type, and reject any override for a name the template never declared."""
    unknown = set(overrides) - set(template.variables)
    if unknown:
        raise TemplateError(
            f"unknown variable(s) passed: {', '.join(sorted(unknown))} "
            f"(not declared in {template.source_path or template.name})"
        )

    resolved: dict[str, Any] = {}
    for var_name, spec in template.variables.items():
        if var_name in overrides:
            raw = overrides[var_name]
        elif spec.default is not None:
            raw = spec.default
        elif spec.required:
            raise TemplateError(f"missing required variable: {var_name!r}")
        else:
            resolved[var_name] = None
            continue
        resolved[var_name] = _coerce(raw, spec.type, var_name)
    return resolved


def render_value(value: Any, resolved_vars: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: render_value(v, resolved_vars) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, resolved_vars) for v in value]
    if isinstance(value, str):
        direct = _DIRECT_SIGIL_RE.match(value)
        if direct:
            var_name = direct.group(1)
            if var_name not in resolved_vars:
                raise TemplateError(f"params reference undeclared variable '${{{var_name}}}'")
            return resolved_vars[var_name]
        try:
            return _jinja_env.from_string(value).render(**resolved_vars)
        except UndefinedError as exc:
            raise TemplateError(f"undefined variable referenced in {value!r}: {exc}") from exc
    return value


def render_template(template: Template, overrides: dict[str, Any]) -> dict[str, Any]:
    """The main entry point: resolve variables, then render params."""
    resolved = resolve_variables(template, overrides)
    return render_value(template.params, resolved)


def find_referenced_variables(value: Any, found: set[str] | None = None) -> set[str]:
    """Recursively collect every variable name referenced anywhere in
    ``value`` (a params tree), via either substitution syntax."""
    if found is None:
        found = set()
    if isinstance(value, dict):
        for v in value.values():
            find_referenced_variables(v, found)
    elif isinstance(value, list):
        for v in value:
            find_referenced_variables(v, found)
    elif isinstance(value, str):
        direct = _DIRECT_SIGIL_RE.match(value)
        if direct:
            found.add(direct.group(1))
        else:
            ast = _jinja_env.parse(value)
            found |= meta.find_undeclared_variables(ast)
    return found


def validate_template(template: Template) -> list[str]:
    """Static validation independent of any specific render call.

    Raises ``TemplateError`` for a hard problem: params reference a
    variable the template never declared. Returns a list of non-fatal
    warning strings for variables that are declared but never referenced
    anywhere in params (almost certainly dead, but not actually broken).
    """
    referenced = find_referenced_variables(template.params)
    declared = set(template.variables)

    undeclared_refs = referenced - declared
    if undeclared_refs:
        raise TemplateError(
            f"params reference undeclared variable(s): {', '.join(sorted(undeclared_refs))}"
        )

    unused = declared - referenced
    return [f"variable {name!r} is declared but never referenced in params" for name in sorted(unused)]
