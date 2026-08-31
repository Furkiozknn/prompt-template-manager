from __future__ import annotations

import pytest

from prompt_template_manager.loader import load_template_str
from prompt_template_manager.models import TemplateError
from prompt_template_manager.renderer import render_template, resolve_variables, validate_template

BASIC = """
name: greet
version: "1"
capability: echo
params:
  message: "hello, {{ who }}!"
  loud: "${shout}"
  count: "${times}"
variables:
  who:
    type: string
    default: world
  shout:
    type: boolean
    default: false
  times:
    type: integer
    default: 1
"""


def test_render_uses_defaults_when_no_overrides():
    template = load_template_str(BASIC)
    rendered = render_template(template, {})
    assert rendered == {"message": "hello, world!", "loud": False, "count": 1}


def test_render_applies_string_override_via_jinja():
    template = load_template_str(BASIC)
    rendered = render_template(template, {"who": "Ada"})
    assert rendered["message"] == "hello, Ada!"


def test_direct_sigil_preserves_boolean_type_not_stringified():
    template = load_template_str(BASIC)
    rendered = render_template(template, {"shout": "true"})
    assert rendered["loud"] is True
    assert isinstance(rendered["loud"], bool)


def test_direct_sigil_preserves_integer_type_not_stringified():
    template = load_template_str(BASIC)
    rendered = render_template(template, {"times": "7"})
    assert rendered["count"] == 7
    assert isinstance(rendered["count"], int)


def test_missing_required_variable_raises():
    src = """
name: x
version: "1"
capability: echo
params:
  a: "{{ required_thing }}"
variables:
  required_thing:
    type: string
    required: true
"""
    template = load_template_str(src)
    with pytest.raises(TemplateError, match="missing required variable"):
        render_template(template, {})


def test_required_variable_provided_via_override_works():
    src = """
name: x
version: "1"
capability: echo
params:
  a: "{{ required_thing }}"
variables:
  required_thing:
    type: string
    required: true
"""
    template = load_template_str(src)
    rendered = render_template(template, {"required_thing": "hi"})
    assert rendered["a"] == "hi"


def test_unknown_override_is_rejected():
    template = load_template_str(BASIC)
    with pytest.raises(TemplateError, match="unknown variable"):
        render_template(template, {"typo_of_who": "Ada"})


def test_integer_coercion_from_cli_style_string():
    resolved = resolve_variables(load_template_str(BASIC), {"times": "42"})
    assert resolved["times"] == 42


def test_integer_coercion_rejects_non_numeric_string():
    with pytest.raises(TemplateError, match="cannot convert"):
        resolve_variables(load_template_str(BASIC), {"times": "not-a-number"})


def test_boolean_coercion_accepts_common_string_forms():
    for truthy in ("true", "True", "1", "yes"):
        resolved = resolve_variables(load_template_str(BASIC), {"shout": truthy})
        assert resolved["shout"] is True
    for falsy in ("false", "False", "0", "no"):
        resolved = resolve_variables(load_template_str(BASIC), {"shout": falsy})
        assert resolved["shout"] is False


def test_nested_dict_and_list_values_are_rendered_recursively():
    src = """
name: x
version: "1"
capability: echo
params:
  outer:
    inner: "{{ subject }}"
    items:
      - "static"
      - "{{ subject }} again"
variables:
  subject:
    type: string
    default: cats
"""
    template = load_template_str(src)
    rendered = render_template(template, {})
    assert rendered["outer"]["inner"] == "cats"
    assert rendered["outer"]["items"] == ["static", "cats again"]


def test_jinja_typo_undeclared_variable_raises():
    src = """
name: x
version: "1"
capability: echo
params:
  a: "{{ this_was_never_declared }}"
"""
    template = load_template_str(src)
    with pytest.raises(TemplateError, match="undefined variable"):
        render_template(template, {})


def test_direct_sigil_undeclared_variable_raises():
    src = """
name: x
version: "1"
capability: echo
params:
  a: "${also_never_declared}"
"""
    template = load_template_str(src)
    with pytest.raises(TemplateError, match="undeclared variable"):
        render_template(template, {})


def test_plain_string_with_no_template_syntax_passes_through():
    src = """
name: x
version: "1"
capability: echo
params:
  a: "just a plain string, no braces here"
"""
    template = load_template_str(src)
    rendered = render_template(template, {})
    assert rendered["a"] == "just a plain string, no braces here"


def test_validate_raises_on_undeclared_reference():
    src = """
name: x
version: "1"
capability: echo
params:
  a: "{{ ghost }}"
"""
    template = load_template_str(src)
    with pytest.raises(TemplateError, match="undeclared variable"):
        validate_template(template)


def test_validate_warns_on_unused_declared_variable():
    src = """
name: x
version: "1"
capability: echo
params:
  a: "static"
variables:
  never_used:
    type: string
    default: x
"""
    template = load_template_str(src)
    warnings = validate_template(template)
    assert len(warnings) == 1
    assert "never_used" in warnings[0]


def test_validate_clean_template_has_no_warnings():
    template = load_template_str(BASIC)
    assert validate_template(template) == []
