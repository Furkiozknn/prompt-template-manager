from __future__ import annotations

from pathlib import Path

import pytest

from prompt_template_manager.loader import load_template_file, load_template_str
from prompt_template_manager.models import TemplateError

VALID_YAML = """
name: greet
version: "1"
capability: echo
params:
  message: "hello, {{ who }}"
variables:
  who:
    type: string
    default: world
"""


def test_load_template_str_parses_valid_yaml():
    template = load_template_str(VALID_YAML)
    assert template.name == "greet"
    assert template.params["message"] == "hello, {{ who }}"


def test_load_template_str_rejects_invalid_yaml():
    with pytest.raises(TemplateError, match="invalid YAML"):
        load_template_str("{ not: valid: yaml: [")


def test_load_template_str_rejects_non_mapping_top_level():
    with pytest.raises(TemplateError, match="must be a YAML mapping"):
        load_template_str("- just\n- a\n- list\n")


def test_load_template_file_reads_and_parses(tmp_path: Path):
    path = tmp_path / "t.yaml"
    path.write_text(VALID_YAML)
    template = load_template_file(path)
    assert template.name == "greet"
    assert template.source_path == str(path)


def test_load_template_file_missing_file_raises(tmp_path: Path):
    with pytest.raises(TemplateError, match="no such file"):
        load_template_file(tmp_path / "does-not-exist.yaml")


def test_shipped_example_template_is_valid():
    repo_root = Path(__file__).resolve().parent.parent
    example = repo_root / "examples" / "product-photo.yaml"
    template = load_template_file(example)
    assert template.name == "product-photo-on-solid-background"
    assert template.capability == "mock-generate"
    assert "product_name" in template.variables
    assert template.variables["product_name"].required is True
