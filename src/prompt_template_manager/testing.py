"""`ptm test`: fixture cases that live next to the template they check.

A template's ``tests:`` list pins what it renders for given variables, the
way promptfoo's ``tests:`` pin what a model answers. Here the check is the
render itself, so it is deterministic, offline and free, which is what a
pre-merge CI step needs: change a prompt's wording or a default and the
case that depended on it fails in the pull request.

.. code-block:: yaml

    tests:
      - name: default background
        vars: {product_name: "a red sneaker"}
        expect:                     # these params, at least (nested mappings
          width: 1024               # are compared key by key)
        contains:
          prompt: ["a red sneaker", "white background"]
        not_contains:
          prompt: "None"
      - name: the product is required
        vars: {}
        error: "missing required variable"   # rendering must fail, saying this

Keys of ``contains`` / ``not_contains`` are dotted paths into the rendered
params (``prompt``, ``options.style``, ``images.0``). ``equals`` compares
the whole rendered params object. Values are compared with their JSON type:
``1`` does not equal ``true`` or ``1.0``-as-a-string.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .models import Template, TemplateError
from .renderer import render_template

CASE_FIELDS = ("name", "vars", "expect", "equals", "contains", "not_contains", "error")
_ASSERTIONS = ("expect", "equals", "contains", "not_contains", "error")


@dataclass
class TestCase:
    __test__ = False  # not a pytest class, whatever its name says

    name: str
    vars: dict[str, Any]
    expect: Optional[dict[str, Any]] = None
    equals: Optional[dict[str, Any]] = None
    contains: dict[str, list[str]] = field(default_factory=dict)
    not_contains: dict[str, list[str]] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class CaseResult:
    name: str
    passed: bool
    failures: list[str] = field(default_factory=list)


def _strings(value: Any, where: str) -> list[str]:
    items = value if isinstance(value, list) else [value]
    if not items or not all(isinstance(item, str) and item for item in items):
        raise TemplateError(f"{where} must be a non-empty string or a list of them")
    return items


def _path_map(value: Any, where: str) -> dict[str, list[str]]:
    if not isinstance(value, dict) or not value:
        raise TemplateError(f"{where} must map a param path to text, e.g. {{prompt: \"a red sneaker\"}}")
    return {str(path): _strings(text, f"{where}.{path}") for path, text in value.items()}


def parse_cases(template: Template) -> list[TestCase]:
    """The template's ``tests:`` list, checked. Raises TemplateError naming
    the case and the problem (unknown key with a did-you-mean, a case with
    no assertion, ``error`` mixed with output assertions, a var the template
    does not declare)."""
    cases: list[TestCase] = []
    seen: set[str] = set()
    for index, raw in enumerate(template.tests):
        label = f"tests[{index}]"
        if not isinstance(raw, dict):
            raise TemplateError(f"{label} must be a mapping")
        unknown = sorted(set(raw) - set(CASE_FIELDS))
        if unknown:
            close = difflib.get_close_matches(unknown[0], CASE_FIELDS, n=1)
            hint = f" (did you mean {close[0]!r}?)" if close else ""
            raise TemplateError(f"{label}: unknown key {unknown[0]!r}{hint}; allowed: {', '.join(CASE_FIELDS)}")
        name = raw.get("name", f"case {index + 1}")
        if not isinstance(name, str) or not name.strip():
            raise TemplateError(f"{label}: 'name' must be a non-empty string")
        if name in seen:
            raise TemplateError(f"{label}: duplicate test name {name!r}")
        seen.add(name)
        label = f"test {name!r}"

        variables = raw.get("vars") or {}
        if not isinstance(variables, dict):
            raise TemplateError(f"{label}: 'vars' must be a mapping of variable name -> value")
        undeclared = sorted(set(variables) - set(template.variables))
        if undeclared:
            known = sorted(template.variables)
            close = difflib.get_close_matches(undeclared[0], known, n=1)
            hint = f" (did you mean {close[0]!r}?)" if close else ""
            raise TemplateError(f"{label}: vars sets undeclared variable {undeclared[0]!r}{hint}")

        present = [key for key in _ASSERTIONS if key in raw]
        if not present:
            raise TemplateError(f"{label}: has no assertion (one of {', '.join(_ASSERTIONS)})")
        if "error" in raw and len(present) > 1:
            raise TemplateError(f"{label}: 'error' expects the render to fail, so it cannot be combined with {present}")

        case = TestCase(name=name, vars=variables)
        for key in ("expect", "equals"):
            if key in raw:
                if not isinstance(raw[key], dict):
                    raise TemplateError(f"{label}: '{key}' must be a mapping of params")
                setattr(case, key, raw[key])
        if "contains" in raw:
            case.contains = _path_map(raw["contains"], f"{label}: contains")
        if "not_contains" in raw:
            case.not_contains = _path_map(raw["not_contains"], f"{label}: not_contains")
        if "error" in raw:
            if not isinstance(raw["error"], str) or not raw["error"]:
                raise TemplateError(f"{label}: 'error' must be a non-empty string expected in the message")
            case.error = raw["error"]
        cases.append(case)
    return cases


def _same(expected: Any, actual: Any) -> bool:
    """Equality that respects JSON types (Python says 1 == True == 1.0)."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(expected) is type(actual) and expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return isinstance(expected, int) == isinstance(actual, int) and expected == actual
    if isinstance(expected, dict) and isinstance(actual, dict):
        return expected.keys() == actual.keys() and all(_same(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(_same(e, a) for e, a in zip(expected, actual))
    return type(expected) is type(actual) and expected == actual


def _subset_failures(expected: dict[str, Any], actual: Any, path: str = "") -> list[str]:
    if not isinstance(actual, dict):
        return [f"{path or 'params'}: expected a mapping, got {json.dumps(actual)}"]
    failures = []
    for key, want in expected.items():
        where = f"{path}.{key}" if path else str(key)
        if key not in actual:
            failures.append(f"{where}: missing from the rendered params")
        elif isinstance(want, dict) and isinstance(actual[key], dict):
            failures += _subset_failures(want, actual[key], where)
        elif not _same(want, actual[key]):
            failures.append(f"{where}: expected {json.dumps(want)}, got {json.dumps(actual[key])}")
    return failures


_MISSING = object()


def _at(params: Any, path: str) -> Any:
    node = params
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return _MISSING
    return node


def run_case(template: Template, case: TestCase) -> CaseResult:
    """Render the template with the case's vars and check every assertion.
    All failures are reported, not only the first."""
    try:
        params = render_template(template, case.vars)
    except TemplateError as exc:
        if case.error is not None:
            if case.error in str(exc):
                return CaseResult(case.name, True)
            return CaseResult(case.name, False, [f"render failed, but not with {case.error!r}: {exc}"])
        return CaseResult(case.name, False, [f"render failed: {exc}"])
    if case.error is not None:
        return CaseResult(case.name, False, [f"expected the render to fail with {case.error!r}, but it succeeded"])

    failures: list[str] = []
    if case.equals is not None and not _same(case.equals, params):
        failures.append(f"params: expected exactly {json.dumps(case.equals)}, got {json.dumps(params)}")
    if case.expect is not None:
        failures += _subset_failures(case.expect, params)
    for path, needles in case.contains.items():
        value = _at(params, path)
        if not isinstance(value, str):
            failures.append(f"{path}: not a string in the rendered params, cannot check contains")
            continue
        failures += [f"{path}: does not contain {needle!r}" for needle in needles if needle not in value]
    for path, needles in case.not_contains.items():
        value = _at(params, path)
        if not isinstance(value, str):
            failures.append(f"{path}: not a string in the rendered params, cannot check not_contains")
            continue
        failures += [f"{path}: contains {needle!r}" for needle in needles if needle in value]
    return CaseResult(case.name, not failures, failures)


def run_tests(template: Template) -> list[CaseResult]:
    """Every case of ``template``. Raises TemplateError for malformed cases."""
    return [run_case(template, case) for case in parse_cases(template)]
