"""A template or vars file can come from someone else. Every shape of hostile
or merely odd input below used to end in a raw traceback, a hang, or output
that is not valid JSON. Each must now be a `TemplateError` naming the problem."""

from __future__ import annotations

import json
import math

import pytest

from prompt_template_manager.loader import load_template_str
from prompt_template_manager.models import TemplateError
from prompt_template_manager.renderer import render_template, validate_template

HEAD = "name: t\nversion: 1\ncapability: echo\n"


def _load(body: str):
    return load_template_str(HEAD + body)


# --- params tree: shapes JSON cannot carry --------------------------------


def test_unquoted_date_in_params_is_rejected_at_load():
    # PyYAML turns 2024-01-01 into datetime.date; json.dumps then crashed
    # `ptm render` with a TypeError traceback while `ptm validate` said OK.
    with pytest.raises(TemplateError, match=r"params\.when.*date.*quote it"):
        _load("params: {when: 2024-01-01}\n")


def test_binary_scalar_in_params_is_rejected():
    with pytest.raises(TemplateError, match=r"params\.blob.*bytes"):
        _load("params: {blob: !!binary aGVsbG8=}\n")


@pytest.mark.parametrize("literal", [".nan", ".inf", "-.inf"])
def test_non_finite_float_in_params_is_rejected(literal):
    # json.dumps writes NaN / Infinity, which is not JSON: the gateway (or
    # anything piping `ptm render`) would get an invalid body.
    with pytest.raises(TemplateError, match="finite"):
        _load(f"params: {{x: {literal}}}\n")


def test_non_string_key_in_params_is_rejected():
    with pytest.raises(TemplateError, match="keys must be strings"):
        _load("params: {1: one}\n")


# --- params tree: YAML aliases ---------------------------------------------


def test_self_referencing_alias_is_rejected_not_recursion_error():
    with pytest.raises(TemplateError, match="nested deeper than"):
        _load("params: &a {self: *a}\n")


def test_alias_bomb_is_rejected_quickly():
    # Each level references the previous one ten times: 10**7 leaves after
    # expansion from a ~600-byte file. `ptm validate` used to hang on it.
    levels = ['  a: &a ["x","x","x","x","x","x","x","x","x","x"]']
    names = "abcdefg"
    for prev, cur in zip(names, names[1:]):
        levels.append(f"  {cur}: &{cur} [" + ",".join([f"*{prev}"] * 10) + "]")
    with pytest.raises(TemplateError, match="too large"):
        _load("params:\n" + "\n".join(levels) + "\n")


def test_ordinary_alias_reuse_still_works():
    t = _load("params:\n  base: &b {w: 1}\n  copy: *b\n")
    assert render_template(t, {}) == {"base": {"w": 1}, "copy": {"w": 1}}


# --- other top-level fields -------------------------------------------------


@pytest.mark.parametrize(
    "field, value",
    [("name", "[1, 2]"), ("name", "''"), ("version", "{a: 1}"), ("description", "[x]")],
)
def test_metadata_fields_must_be_scalars(field, value):
    base = {"name": "t", "version": "1", "description": "d"}
    base[field] = value
    text = "".join(f"{k}: {v}\n" for k, v in base.items()) + "capability: echo\nparams: {}\n"
    with pytest.raises(TemplateError, match=field):
        load_template_str(text)


def test_non_string_variable_name_is_rejected():
    # `variables: {1: ...}` crashed render with "keywords must be strings".
    with pytest.raises(TemplateError, match="variable names must be strings"):
        _load("variables: {1: {default: a}}\nparams: {p: x}\n")


def test_non_scalar_default_is_rejected():
    with pytest.raises(TemplateError, match="default"):
        _load("variables: {v: {default: [1, 2]}}\nparams: {p: '{{ v }}'}\n")


# --- values passed in (--var / --vars-file / library overrides) ------------

STR_VAR = "variables: {v: {type: string}, n: {type: float, default: 1.0}}\nparams: {p: '{{ v }}', n: '${n}'}\n"


@pytest.mark.parametrize("value", [["a", "b"], {"k": "v"}])
def test_non_scalar_override_is_rejected(value):
    # A vars file entry `v: [a, b]` used to reach the model as "['a', 'b']".
    with pytest.raises(TemplateError, match="'v'.*single value"):
        render_template(_load(STR_VAR), {"v": value})


def test_empty_override_is_rejected_not_rendered_as_None():
    # A vars file line `v:` (no value) is None; str(None) sent the word
    # "None" to the model - the exact bug fixed for unset optionals.
    with pytest.raises(TemplateError, match="'v'.*no value"):
        render_template(_load(STR_VAR), {"v": None})


@pytest.mark.parametrize("raw", ["nan", "inf", "-Infinity", math.inf])
def test_non_finite_float_override_is_rejected(raw):
    with pytest.raises(TemplateError, match="'n'.*finite"):
        render_template(_load(STR_VAR), {"v": "x", "n": raw})


def test_rendered_output_is_always_strict_json():
    out = render_template(_load(STR_VAR), {"v": "x", "n": "2.5"})
    json.dumps(out, allow_nan=False)


# --- Jinja evaluation --------------------------------------------------------


@pytest.mark.parametrize(
    "expr",
    ["{{ 1/0 }}", "{{ 'a' + 1 }}", "{{ range(10**6) | list }}"],
)
def test_runtime_errors_inside_jinja_become_template_errors(expr):
    t = _load(f"params: {{p: \"{expr}\"}}\n")
    with pytest.raises(TemplateError, match="error while rendering"):
        render_template(t, {})


def test_huge_power_is_refused_instead_of_hanging():
    t = _load('params: {p: "{{ 10 ** (10 ** 9) }}"}\n')
    with pytest.raises(TemplateError, match="unsafe operation"):
        render_template(t, {})


def test_huge_string_repetition_is_refused_instead_of_memory_error():
    t = _load("params: {p: \"{{ 'a' * 3000000000 }}\"}\n")
    with pytest.raises(TemplateError, match="unsafe operation"):
        render_template(t, {})


def test_ordinary_arithmetic_still_works():
    t = _load("params: {p: \"{{ 2 ** 10 }} {{ '-' * 3 }} {{ 6 * 7 }}\"}\n")
    assert render_template(t, {}) == {"p": "1024 --- 42"}


def test_validate_rejects_what_render_would_reject():
    # validate must not say OK for a template render cannot serialise.
    with pytest.raises(TemplateError):
        validate_template(_load("params: {when: 2024-01-01}\n"))


def test_hand_built_template_is_checked_too():
    from prompt_template_manager.models import Template

    loop: dict = {}
    loop["self"] = loop
    t = Template(name="t", version="1", capability="echo", params=loop)
    for call in (lambda: render_template(t, {}), lambda: validate_template(t)):
        with pytest.raises(TemplateError, match="nested deeper"):
            call()
