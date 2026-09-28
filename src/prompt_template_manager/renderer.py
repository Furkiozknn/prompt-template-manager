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

import difflib
import math
import operator
import re
from typing import Any

from jinja2 import StrictUndefined, UndefinedError, meta
from jinja2.exceptions import SecurityError, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment

from .models import Template, TemplateError, check_json_tree

_DIRECT_SIGIL_RE = re.compile(r"^\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}$")
_EMBEDDED_SIGIL_RE = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

# Templates are loaded from files, and a template file can come from a
# third party (shared, downloaded, pulled from a registry) just as easily
# as a source file can. A plain jinja2.Environment gives a template full
# Python object access (``{{ ''.__class__.__mro__[1].__subclasses__() }}``
# and friends) which is a real code-execution surface, not a theoretical
# one - see the README's Security section. SandboxedEnvironment blocks
# attribute/method access outside an allow-list while leaving ordinary
# variable interpolation (the only thing legitimate templates here do)
# completely unaffected.
#
# The sandbox guards object access, not resource use: ``{{ 10 ** (10 ** 9) }}``
# hung the process and ``{{ 'a' * 3000000000 }}`` exhausted memory. Those two
# operators are the one-token ways to do it, so they are bounded here. This
# is not a CPU/memory limit for Jinja as a whole (nested loops can still spin)
# - the README says so and suggests `timeout` for untrusted files.
_MAX_POWER_BITS = 4096
_MAX_REPEAT_LEN = 100_000


class _BoundedSandbox(SandboxedEnvironment):
    intercepted_binops = frozenset(["*", "**"])

    def call_binop(self, context: Any, operator_name: str, left: Any, right: Any) -> Any:
        if operator_name == "**":
            if isinstance(left, int) and isinstance(right, int) and right > 0:
                if abs(left) > 1 and abs(left).bit_length() * right > _MAX_POWER_BITS:
                    raise SecurityError(f"{left!r} ** {right!r} is too large to compute")
            elif isinstance(right, (int, float)) and abs(right) > _MAX_POWER_BITS:
                raise SecurityError(f"exponent {right!r} is too large")
            return operator.pow(left, right)
        if operator_name == "*":
            for seq, count in ((left, right), (right, left)):
                if isinstance(seq, (str, list, tuple)) and isinstance(count, int) and not isinstance(count, bool):
                    if len(seq) * count > _MAX_REPEAT_LEN:
                        raise SecurityError(
                            f"repeating a {type(seq).__name__} {count} times exceeds {_MAX_REPEAT_LEN} items"
                        )
            return operator.mul(left, right)
        return super().call_binop(context, operator_name, left, right)  # pragma: no cover


_jinja_env = _BoundedSandbox(undefined=StrictUndefined)


def _coerce(value: Any, var_type: str, var_name: str) -> Any:
    if value is None:
        raise TemplateError(
            f"variable {var_name!r}: no value given (an empty entry in a vars file?); "
            "leave it out to use the default"
        )
    if isinstance(value, (dict, list, tuple, set)):
        raise TemplateError(
            f"variable {var_name!r}: expected a single value, got a {type(value).__name__} "
            "(a --vars-file entry must be a string, number or boolean)"
        )
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
        try:
            result = float(value) if isinstance(value, (int, float)) else float(str(value))
        except (ValueError, OverflowError):
            raise TemplateError(f"variable {var_name!r}: cannot convert {value!r} to float")
        if not math.isfinite(result):
            # json.dumps would write NaN / Infinity - not JSON, so not a
            # request body any gateway is obliged to parse.
            raise TemplateError(f"variable {var_name!r}: {value!r} is not a finite number")
        return result
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


def _describe_unknown(name: str, known: list[str]) -> str:
    suggestions = difflib.get_close_matches(name, known, n=1)
    if suggestions:
        return f"{name!r} (did you mean {suggestions[0]!r}?)"
    return repr(name)


def resolve_variables(template: Template, overrides: dict[str, Any]) -> dict[str, Any]:
    """Merge CLI/caller-supplied overrides with declared defaults, validate
    required variables are present, coerce every value to its declared
    type, and reject any override for a name the template never declared."""
    known = list(template.variables)
    unknown = set(overrides) - set(known)
    if unknown:
        described = ", ".join(_describe_unknown(name, known) for name in sorted(unknown))
        raise TemplateError(
            f"unknown variable(s) passed: {described} "
            f"(not declared in {template.source_path or template.name})"
        )

    missing = [
        name
        for name, spec in template.variables.items()
        if name not in overrides and spec.default is None and spec.required
    ]
    if missing:
        named = ", ".join(repr(name) for name in missing)
        raise TemplateError(
            f"missing required variable(s): {named} "
            "-- pass with --var name=value (or --vars-file), or add a default in the template"
        )

    resolved: dict[str, Any] = {}
    for var_name, spec in template.variables.items():
        if var_name in overrides:
            raw = overrides[var_name]
        elif spec.default is not None:
            raw = spec.default
        else:
            resolved[var_name] = None
            continue
        resolved[var_name] = _coerce(raw, spec.type, var_name)
    return resolved


def _jinja_context(resolved_vars: dict[str, Any]) -> dict[str, Any]:
    """The render context for string interpolation.

    A declared-but-unset optional resolves to ``None``, which is the honest
    typed value for a ``${var}`` slot. Handed to Jinja, though, ``None``
    stringifies: ``"a {{ style }} photo"`` came out as ``"a None photo"`` -
    a word the user never wrote, silently sent on to the model. Inside a
    string an unset optional contributes nothing, so it renders as empty.
    ``StrictUndefined`` is untouched: a *typo'd* name is still an error,
    because it never reaches this dict at all.
    """
    return {name: ("" if value is None else value) for name, value in resolved_vars.items()}


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
            return _jinja_env.from_string(value).render(**_jinja_context(resolved_vars))
        except TemplateSyntaxError as exc:
            # Without this, a malformed template ({{ foo, {% if %}) walked a
            # raw Jinja traceback out through the CLI - the same bug class
            # ai-workflow-engine already fixed. Same translation here.
            raise TemplateError(
                f"template syntax error in {value!r} (line {exc.lineno}): {exc.message}"
            ) from exc
        except UndefinedError as exc:
            raise TemplateError(f"undefined variable referenced in {value!r}: {exc}") from exc
        except SecurityError as exc:
            raise TemplateError(
                f"template attempted an unsafe operation in {value!r}: {exc} "
                "(templates render in a sandboxed Jinja2 environment; only variable "
                "interpolation and safe filters are permitted, see README Security section)"
            ) from exc
        except (ArithmeticError, TypeError, ValueError, LookupError, AttributeError, RuntimeError) as exc:
            # {{ 1/0 }}, {{ 'a' + 1 }}, range() over the sandbox limit, ...:
            # a bug in the template, reported as one rather than a traceback.
            raise TemplateError(
                f"error while rendering {value!r}: {type(exc).__name__}: {exc}"
            ) from exc
    return value


def render_template(template: Template, overrides: dict[str, Any]) -> dict[str, Any]:
    """The main entry point: resolve variables, then render params."""
    # from_dict already checked this; a Template built by hand in library
    # code has not been, and the walk below must not meet an alias bomb.
    check_json_tree(template.params)
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
            try:
                ast = _jinja_env.parse(value)
            except TemplateSyntaxError as exc:
                raise TemplateError(
                    f"template syntax error in {value!r} (line {exc.lineno}): {exc.message}"
                ) from exc
            found |= meta.find_undeclared_variables(ast)
    return found


def _find_embedded_sigils(value: Any, path: str = "") -> list[tuple[str, str]]:
    """(param path, variable name) for every ``${var}`` that is only *part*
    of a string. Such a sigil is not substituted - it reaches the model
    literally, which is exactly the silent failure this tool exists to stop."""
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, v in value.items():
            found += _find_embedded_sigils(v, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, v in enumerate(value):
            found += _find_embedded_sigils(v, f"{path}[{index}]")
    elif isinstance(value, str) and not _DIRECT_SIGIL_RE.match(value):
        found += [(path, m.group(1)) for m in _EMBEDDED_SIGIL_RE.finditer(value)]
    return found


def validate_template(template: Template) -> list[str]:
    """Static validation independent of any specific render call.

    Raises ``TemplateError`` for a hard problem: params reference a
    variable the template never declared. Returns a list of non-fatal
    warning strings for variables that are declared but never referenced
    anywhere in params (almost certainly dead, but not actually broken),
    and for a ``${var}`` embedded in a longer string (sent literally).

    Also raises if a declared ``default`` cannot be coerced to the
    variable's declared type - that template could never render with its
    defaults, so it should not pass validation.
    """
    check_json_tree(template.params)
    for var_name, spec in template.variables.items():
        if spec.default is not None:
            try:
                _coerce(spec.default, spec.type, var_name)
            except TemplateError as exc:
                raise TemplateError(f"invalid default: {exc}") from exc

    referenced = find_referenced_variables(template.params)
    declared = set(template.variables)

    undeclared_refs = referenced - declared
    if undeclared_refs:
        raise TemplateError(
            f"params reference undeclared variable(s): {', '.join(sorted(undeclared_refs))}"
        )

    unused = declared - referenced
    warnings = [f"variable {name!r} is declared but never referenced in params" for name in sorted(unused)]
    for param_path, var_name in _find_embedded_sigils(template.params):
        warnings.append(
            f"param {param_path!r}: '${{{var_name}}}' is only part of the string, so it is sent literally "
            f"(use '{{{{ {var_name} }}}}' inside a string, or make '${{{var_name}}}' the whole value)"
        )
    return warnings
