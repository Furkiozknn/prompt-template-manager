"""`ptm diff`: semantic diff between two template versions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prompt_template_manager import cli
from prompt_template_manager.diffing import (
    BREAKING,
    COSMETIC,
    OUTPUT,
    diff_templates,
    format_diff,
)
from prompt_template_manager.loader import load_template_file, load_template_str

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "product-photo.yaml"

OLD = """
name: photo
version: "1"
capability: mock-generate
description: old text
variables:
  subject: {type: string, required: true}
  width: {type: integer, default: 1024}
  seed: {type: integer, default: 0}
  style: {type: string, default: film}
params:
  prompt: "a studio photo of {{ subject }}, soft even lighting, high detail"
  width: "${width}"
  seed: "${seed}"
  extra: {steps: 30}
"""

NEW = """
name: photo
version: "2"
capability: mock-generate
description: new text
variables:
  subject: {type: string, required: true}
  width: {type: integer, default: 768}
  style: {type: string, required: true}
  mood: {type: string, default: calm}
params:
  prompt: "a studio photo of {{ subject }} in {{ style }}, soft warm lighting, high detail, {{ mood }}"
  width: "${width}"
  extra: {steps: 40, sampler: euler}
"""


def _kinds(diff):
    return [(c.kind, c.where) for c in diff.changes]


def test_changes_are_classified_and_breaking_come_first():
    diff = diff_templates(load_template_str(OLD), load_template_str(NEW))
    kinds = _kinds(diff)
    assert kinds[:2] == [(BREAKING, "variables.seed"), (BREAKING, "variables.style")]
    assert (OUTPUT, "variables.mood") in kinds
    assert (OUTPUT, "variables.width") in kinds
    assert (OUTPUT, "params.seed") in kinds
    assert (OUTPUT, "params.extra.steps") in kinds
    assert (OUTPUT, "params.extra.sampler") in kinds
    assert (COSMETIC, "description") in kinds
    by_where: dict[str, list[str]] = {}
    for c in diff.changes:
        by_where.setdefault(c.where, []).append(c.message)
    assert by_where["variables.width"] == ["default 1024 -> 768"]
    assert by_where["variables.style"] == ["now required", 'default "film" -> null']
    (prompt,) = by_where["params.prompt"]
    assert "[-even-]" in prompt and "{+warm+}" in prompt
    assert diff.count(BREAKING) == 2


@pytest.mark.parametrize(
    "change, kind, where, message",
    [
        ("capability: other", BREAKING, "capability", "'mock-generate' -> 'other' (a different endpoint)"),
        ("variables: {subject: {type: integer, required: true}}", BREAKING, "variables.subject", "type string -> integer"),
        ("variables: {subject: {type: string}}", OUTPUT, "variables.subject", "no longer required"),
        ("variables: {subject: {type: string, required: true}, n: {type: integer, required: true}}",
         BREAKING, "variables.n", "added as required (integer)"),
    ],
)
def test_single_changes(change, kind, where, message):
    base = 'name: t\nversion: "1"\ncapability: mock-generate\nvariables: {subject: {type: string, required: true}}\nparams: {prompt: "{{ subject }}"}\n'
    changed = base
    key = change.split(":", 1)[0]
    lines = [line for line in base.splitlines() if not line.startswith(key + ":")]
    changed = "\n".join(lines) + "\n" + change + "\n"
    if key == "variables" and "n:" in change:
        changed = changed.replace('params: {prompt: "{{ subject }}"}', 'params: {prompt: "{{ subject }} {{ n }}"}')
    diff = diff_templates(load_template_str(base), load_template_str(changed))
    match = [c for c in diff.changes if c.where == where]
    assert match and match[0].kind == kind and match[0].message == message


def test_identical_templates_have_no_changes_and_no_version_problem():
    diff = diff_templates(load_template_file(EXAMPLE), load_template_file(EXAMPLE))
    assert diff.changes == []
    assert diff.version_problem() is None
    assert "no changes" in format_diff(diff)


def test_version_rules():
    old = load_template_str(OLD)
    same_version = load_template_str(NEW.replace('version: "2"', 'version: "1"'))
    assert "bump 'version'" in diff_templates(old, same_version).version_problem()

    minor_only = load_template_str(OLD.replace('version: "1"', 'version: "1.2.0"'))
    breaking_minor = load_template_str(NEW.replace('version: "2"', 'version: "1.3.0"'))
    assert "need a new major version" in diff_templates(minor_only, breaking_minor).version_problem()

    assert diff_templates(old, load_template_str(NEW)).version_problem() is None

    # Non-numeric versions only have to differ.
    named_old = load_template_str(OLD.replace('version: "1"', "version: spring"))
    named_new = load_template_str(NEW.replace('version: "2"', "version: summer"))
    assert diff_templates(named_old, named_new).version_problem() is None

    # A cosmetic-only change needs no bump.
    cosmetic = load_template_str(OLD.replace("old text", "reworded"))
    assert diff_templates(old, cosmetic).version_problem() is None


def test_types_count_as_changes_even_when_python_says_equal():
    old = load_template_str('name: t\nversion: "1"\ncapability: c\nparams: {n: 1}\n')
    new = load_template_str('name: t\nversion: "1"\ncapability: c\nparams: {n: true}\n')
    (change,) = diff_templates(old, new).changes
    assert change.message == "1 -> true"


def _cli(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["ptm", *argv])
    cli.main()


@pytest.fixture
def pair(tmp_path):
    old, new = tmp_path / "old.yaml", tmp_path / "new.yaml"
    old.write_text(OLD, encoding="utf-8")
    new.write_text(NEW, encoding="utf-8")
    return str(old), str(new)


def test_cli_prints_the_diff_and_exits_zero(pair, monkeypatch, capsys):
    _cli(monkeypatch, "diff", *pair)
    out = capsys.readouterr().out
    assert out.startswith("photo: v1 -> v2")
    assert "  BREAKING  variables.seed: removed" in out
    assert "2 breaking, " in out


def test_cli_json(pair, monkeypatch, capsys):
    _cli(monkeypatch, "diff", *pair, "--json")
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["breaking"] == 2
    assert payload["version_problem"] is None
    assert payload["changes"][0] == {
        "kind": "breaking",
        "where": "variables.seed",
        "message": "removed (a caller still passing it gets 'unknown variable')",
    }


def test_cli_check_version_and_fail_on_breaking(pair, tmp_path, monkeypatch, capsys):
    _cli(monkeypatch, "diff", *pair, "--check-version")  # 1 -> 2 is fine
    capsys.readouterr()

    unbumped = tmp_path / "unbumped.yaml"
    unbumped.write_text(NEW.replace('version: "2"', 'version: "1"'), encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        _cli(monkeypatch, "diff", pair[0], str(unbumped), "--check-version")
    assert exc_info.value.code == 1
    assert "bump 'version'" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc_info:
        _cli(monkeypatch, "diff", *pair, "--fail-on-breaking")
    assert exc_info.value.code == 1
    assert "2 breaking change(s)" in capsys.readouterr().err


def test_cli_reports_an_unreadable_template(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc_info:
        _cli(monkeypatch, "diff", str(tmp_path / "missing.yaml"), str(EXAMPLE))
    assert exc_info.value.code == 1
    assert "error:" in capsys.readouterr().err
