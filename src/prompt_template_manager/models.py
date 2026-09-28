"""The template data model.

A template is a plain YAML file - that's the whole point. No database, no
opaque blob format: `git diff` on two versions of a template should show
exactly what changed (a word in a prompt, a default value, a new variable),
the same way it shows a code change. This module just gives that YAML shape
a name and some validation; it stays deliberately close to "a dict with a
schema," not a heavyweight object model.
"""

from __future__ import annotations

import math
import re
import reprlib
from dataclasses import dataclass, field
from typing import Any, Optional

ALLOWED_VARIABLE_TYPES = ("string", "integer", "float", "boolean")

# `capability` becomes a URL path segment: `ptm submit` POSTs to
# {gateway-url}/v1/{capability}. A template can come from a third party, so
# it must not be able to smuggle in "/", "..", "?" or "#" and point the
# request at a different endpoint of the gateway. ai-job-gateway itself
# accepts [A-Za-z0-9_-]; "." is allowed here (not as the first character)
# for other servers implementing the same contract.
_CAPABILITY_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,99}")


# `params` is sent as a JSON request body. YAML aliases are references, so a
# few hundred bytes of `&a [*a, *a, ...]` expand into millions of nodes the
# moment anything walks the tree (validate, render, json.dumps) - and a
# self-referencing alias never ends. No real prompt request comes near
# these limits; they only exist so a hostile file fails fast.
MAX_PARAMS_NODES = 10_000
MAX_PARAMS_DEPTH = 32

_SCALARS = (str, int, float, bool)


def _show(value: Any) -> str:
    """repr() for error messages that never expands an alias bomb."""
    return reprlib.repr(value)


class TemplateError(Exception):
    """Raised for any malformed template: bad YAML shape, unknown variable
    type, a variable declared but never used, a variable used but never
    declared, etc. Always carries a message naming the specific problem and
    (where relevant) the template's file path."""


def check_json_tree(value: Any, where: str = "params") -> None:
    """Raise TemplateError unless ``value`` is plain JSON of bounded size:
    mappings with string keys, lists, strings, finite numbers, booleans and
    null. PyYAML also produces dates, bytes, sets and NaN, none of which a
    JSON request body can carry, and aliases that expand without bound."""
    budget = [MAX_PARAMS_NODES]

    def walk(node: Any, path: str, depth: int) -> None:
        budget[0] -= 1
        if budget[0] < 0:
            raise TemplateError(
                f"{where} is too large: more than {MAX_PARAMS_NODES} values once YAML aliases are expanded"
            )
        if depth > MAX_PARAMS_DEPTH:
            shown = path if len(path) <= 60 else f"{path[:40]}...{path[-15:]}"
            raise TemplateError(
                f"{shown} is nested deeper than {MAX_PARAMS_DEPTH} levels "
                "(or refers to itself through a YAML alias)"
            )
        if isinstance(node, dict):
            for key, child in node.items():
                if not isinstance(key, str):
                    raise TemplateError(f"{path}: keys must be strings, got {_show(key)} ({type(key).__name__})")
                walk(child, f"{path}.{key}", depth + 1)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}[{index}]", depth + 1)
        elif isinstance(node, float):
            if not math.isfinite(node):
                raise TemplateError(f"{path}: {_show(node)} is not a finite number, and JSON cannot carry it")
        elif node is not None and not isinstance(node, _SCALARS):
            raise TemplateError(
                f"{path}: YAML read {_show(node)} as a {type(node).__name__}, which JSON cannot carry "
                "- quote it to send it as a string"
            )

    walk(value, where, 0)


def _require_text(data: dict[str, Any], key: str, *, allow_numbers: bool = False, allow_empty: bool = True) -> str:
    value = data.get(key, "")
    ok_types: tuple[type, ...] = (str, int, float) if allow_numbers else (str,)
    if isinstance(value, bool) or not isinstance(value, ok_types):
        raise TemplateError(f"'{key}' must be a {'string or number' if allow_numbers else 'string'}, got {_show(value)}")
    text = str(value)
    if not allow_empty and not text.strip():
        raise TemplateError(f"'{key}' must not be empty")
    return text


@dataclass
class VariableSpec:
    name: str
    type: str = "string"
    required: bool = False
    default: Any = None
    description: str = ""

    def __post_init__(self) -> None:
        if self.type not in ALLOWED_VARIABLE_TYPES:
            raise TemplateError(
                f"variable {self.name!r}: type must be one of {ALLOWED_VARIABLE_TYPES}, got {_show(self.type)}"
            )
        if self.default is not None and (
            isinstance(self.default, (dict, list)) or not isinstance(self.default, _SCALARS)
        ):
            raise TemplateError(
                f"variable {self.name!r}: default must be a single string, number or boolean, "
                f"got {_show(self.default)}"
            )
        if self.required and self.default is not None:
            raise TemplateError(
                f"variable {self.name!r}: required=true and a default are mutually exclusive "
                "(a required variable, by definition, has no default)"
            )


@dataclass
class Template:
    name: str
    version: str
    capability: str
    params: dict[str, Any]
    description: str = ""
    variables: dict[str, VariableSpec] = field(default_factory=dict)
    source_path: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, source_path: Optional[str] = None) -> "Template":
        missing = [k for k in ("name", "version", "capability", "params") if k not in data]
        if missing:
            raise TemplateError(f"template missing required field(s): {', '.join(missing)}")
        capability = data["capability"]
        if not isinstance(capability, str) or not _CAPABILITY_RE.fullmatch(capability):
            raise TemplateError(
                f"'capability' must be a single URL path segment "
                f"(letters, digits, '_', '-', '.'; not starting with '.'), got {_show(capability)}"
            )
        if not isinstance(data["params"], dict):
            raise TemplateError("'params' must be a mapping (object), not a list or scalar")
        check_json_tree(data["params"])
        name = _require_text(data, "name", allow_empty=False)
        version = _require_text(data, "version", allow_numbers=True, allow_empty=False)
        description = _require_text(data, "description")

        raw_vars = data.get("variables") or {}
        if not isinstance(raw_vars, dict):
            raise TemplateError("'variables' must be a mapping of name -> spec")

        variables: dict[str, VariableSpec] = {}
        for var_name, spec in raw_vars.items():
            if not isinstance(var_name, str):
                raise TemplateError(f"variable names must be strings, got {_show(var_name)}")
            spec = spec or {}
            if not isinstance(spec, dict):
                raise TemplateError(f"variable {_show(var_name)}: spec must be a mapping, got {type(spec).__name__}")
            required = spec.get("required", False)
            if not isinstance(required, bool):
                # bool("false") is True - a quoted `required: "false"` would
                # otherwise silently make the variable required.
                raise TemplateError(
                    f"variable {_show(var_name)}: 'required' must be true or false (unquoted), got {_show(required)}"
                )
            variables[var_name] = VariableSpec(
                name=var_name,
                type=spec.get("type", "string"),
                required=required,
                default=spec.get("default"),
                description=_require_text(spec, "description"),
            )

        return cls(
            name=name,
            version=version,
            capability=capability,
            params=data["params"],
            description=description,
            variables=variables,
            source_path=source_path,
        )
