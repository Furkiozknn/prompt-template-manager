"""The template data model.

A template is a plain YAML file - that's the whole point. No database, no
opaque blob format: `git diff` on two versions of a template should show
exactly what changed (a word in a prompt, a default value, a new variable),
the same way it shows a code change. This module just gives that YAML shape
a name and some validation; it stays deliberately close to "a dict with a
schema," not a heavyweight object model.
"""

from __future__ import annotations

import re
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


class TemplateError(Exception):
    """Raised for any malformed template: bad YAML shape, unknown variable
    type, a variable declared but never used, a variable used but never
    declared, etc. Always carries a message naming the specific problem and
    (where relevant) the template's file path."""


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
                f"variable {self.name!r}: type must be one of {ALLOWED_VARIABLE_TYPES}, got {self.type!r}"
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
                f"(letters, digits, '_', '-', '.'; not starting with '.'), got {capability!r}"
            )
        if not isinstance(data["params"], dict):
            raise TemplateError("'params' must be a mapping (object), not a list or scalar")

        raw_vars = data.get("variables") or {}
        if not isinstance(raw_vars, dict):
            raise TemplateError("'variables' must be a mapping of name -> spec")

        variables: dict[str, VariableSpec] = {}
        for var_name, spec in raw_vars.items():
            spec = spec or {}
            if not isinstance(spec, dict):
                raise TemplateError(f"variable {var_name!r}: spec must be a mapping, got {type(spec).__name__}")
            required = spec.get("required", False)
            if not isinstance(required, bool):
                # bool("false") is True - a quoted `required: "false"` would
                # otherwise silently make the variable required.
                raise TemplateError(
                    f"variable {var_name!r}: 'required' must be true or false (unquoted), got {required!r}"
                )
            variables[var_name] = VariableSpec(
                name=var_name,
                type=spec.get("type", "string"),
                required=required,
                default=spec.get("default"),
                description=spec.get("description", ""),
            )

        return cls(
            name=data["name"],
            version=str(data["version"]),
            capability=capability,
            params=data["params"],
            description=data.get("description", ""),
            variables=variables,
            source_path=source_path,
        )
