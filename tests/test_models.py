from __future__ import annotations

import pytest

from prompt_template_manager.models import Template, TemplateError, VariableSpec


def test_variable_spec_rejects_unknown_type():
    with pytest.raises(TemplateError, match="type must be one of"):
        VariableSpec(name="x", type="not-a-real-type")


def test_variable_spec_rejects_required_with_default():
    with pytest.raises(TemplateError, match="mutually exclusive"):
        VariableSpec(name="x", required=True, default="fallback")


def test_template_from_dict_requires_name_version_capability_params():
    with pytest.raises(TemplateError, match="missing required field"):
        Template.from_dict({"name": "x"})


def test_template_from_dict_requires_params_to_be_a_mapping():
    with pytest.raises(TemplateError, match="'params' must be a mapping"):
        Template.from_dict({"name": "x", "version": "1", "capability": "echo", "params": ["not", "a", "dict"]})


def test_template_from_dict_minimal_valid():
    template = Template.from_dict(
        {"name": "x", "version": "1", "capability": "echo", "params": {"prompt": "hi"}}
    )
    assert template.name == "x"
    assert template.variables == {}


def test_template_from_dict_parses_variables():
    data = {
        "name": "x",
        "version": "2",
        "capability": "echo",
        "params": {"prompt": "{{ subject }}"},
        "variables": {
            "subject": {"type": "string", "required": True, "description": "what to say"},
        },
    }
    template = Template.from_dict(data)
    assert template.variables["subject"].required is True
    assert template.variables["subject"].description == "what to say"


def test_template_from_dict_rejects_non_mapping_variable_spec():
    data = {
        "name": "x",
        "version": "1",
        "capability": "echo",
        "params": {},
        "variables": {"subject": "not-a-mapping"},
    }
    with pytest.raises(TemplateError, match="spec must be a mapping"):
        Template.from_dict(data)


def _minimal(**overrides):
    data = {"name": "x", "version": "1", "capability": "echo", "params": {"prompt": "hi"}}
    data.update(overrides)
    return data


@pytest.mark.parametrize("value", ["false", "no", 0, 1, "true"])
def test_required_must_be_a_real_boolean(value):
    # bool("false") is True: a quoted `required: "false"` used to silently
    # make the variable required.
    with pytest.raises(TemplateError, match="'required' must be true or false"):
        Template.from_dict(_minimal(variables={"v": {"required": value}}))


def test_required_boolean_still_accepted():
    template = Template.from_dict(_minimal(variables={"v": {"required": False}}))
    assert template.variables["v"].required is False


@pytest.mark.parametrize("capability", ["../admin", "a/b", "echo?x=1", "", ".", "..", "has space", "echo\n", 123, None])
def test_capability_must_be_a_single_url_path_segment(capability):
    # It is interpolated into {gateway-url}/v1/{capability}; a third-party
    # template must not be able to point `ptm submit` at another endpoint.
    with pytest.raises(TemplateError, match="capability"):
        Template.from_dict(_minimal(capability=capability))


@pytest.mark.parametrize("capability", ["echo", "mock-generate", "text_to_image", "v2.render"])
def test_capability_accepts_ordinary_names(capability):
    assert Template.from_dict(_minimal(capability=capability)).capability == capability
