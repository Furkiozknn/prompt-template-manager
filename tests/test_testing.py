"""`ptm test`: fixture cases in a template's `tests:` list."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from prompt_template_manager import cli
from prompt_template_manager.loader import load_template_str
from prompt_template_manager.models import TemplateError
from prompt_template_manager.testing import parse_cases, run_tests

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "product-photo.yaml"

BASE = """
name: t
version: "1"
capability: mock-generate
variables:
  subject: {type: string, required: true}
  steps: {type: integer, default: 30}
  hd: {type: boolean, default: false}
params:
  prompt: "a photo of {{ subject }}"
  steps: "${steps}"
  hd: "${hd}"
  options: {style: "film"}
"""


def _template(tests_yaml: str):
    return load_template_str(BASE + textwrap.dedent(tests_yaml))


def test_passing_cases_cover_every_assertion_kind():
    template = _template(
        """
        tests:
          - name: subset
            vars: {subject: cat}
            expect: {steps: 30, options: {style: film}}
          - name: whole object
            vars: {subject: cat, steps: "5"}
            equals: {prompt: "a photo of cat", steps: 5, hd: false, options: {style: film}}
          - name: text
            vars: {subject: a red cat}
            contains: {prompt: ["red", "photo"], options.style: film}
            not_contains: {prompt: None}
          - name: fails loudly
            vars: {}
            error: missing required variable
        """
    )
    results = run_tests(template)
    assert [r.passed for r in results] == [True, True, True, True]


def test_failures_are_all_reported_with_paths_and_values():
    template = _template(
        """
        tests:
          - name: wrong
            vars: {subject: dog}
            expect: {steps: 31, missing_key: 1, options: {style: noir}}
            contains: {prompt: [cat, photo]}
            not_contains: {prompt: dog}
        """
    )
    (result,) = run_tests(template)
    assert not result.passed
    assert result.failures == [
        "steps: expected 31, got 30",
        "missing_key: missing from the rendered params",
        'options.style: expected "noir", got "film"',
        "prompt: does not contain 'cat'",
        "prompt: contains 'dog'",
    ]


def test_json_types_are_respected():
    template = _template(
        """
        tests:
          - name: int is not bool
            vars: {subject: x}
            expect: {hd: 0}
          - name: string is not int
            vars: {subject: x}
            expect: {steps: "30"}
        """
    )
    assert [r.passed for r in run_tests(template)] == [False, False]


def test_error_cases_fail_when_the_render_succeeds_or_fails_differently():
    template = _template(
        """
        tests:
          - name: should fail but does not
            vars: {subject: x}
            error: missing required
          - name: fails with another message
            vars: {subject: x, steps: many}
            error: missing required
          - name: unexpected render error
            vars: {subject: x, steps: many}
            expect: {steps: 1}
        """
    )
    a, b, c = run_tests(template)
    assert not a.passed and "but it succeeded" in a.failures[0]
    assert not b.passed and "cannot convert 'many' to integer" in b.failures[0]
    assert not c.passed and c.failures[0].startswith("render failed:")


@pytest.mark.parametrize(
    "tests_yaml, message",
    [
        ("tests: {a: 1}", "'tests' must be a list"),
        ("tests: [1]", "tests[0] must be a mapping"),
        ("tests: [{name: x, vars: {subject: a}, expcet: {}}]", "unknown key 'expcet' (did you mean 'expect'?)"),
        ("tests: [{name: x, vars: {subject: a}}]", "has no assertion"),
        ("tests: [{name: x, vars: {subjet: a}, expect: {}}]", "undeclared variable 'subjet' (did you mean 'subject'?)"),
        ("tests: [{name: x, vars: {}, error: e, expect: {}}]", "cannot be combined"),
        ("tests: [{name: x, expect: {}}, {name: x, expect: {}}]", "duplicate test name 'x'"),
        ("tests: [{name: x, contains: {prompt: 3}}]", "non-empty string or a list"),
        ("tests: [{name: x, contains: []}]", "must map a param path"),
    ],
)
def test_malformed_cases_are_template_errors(tests_yaml, message):
    with pytest.raises(TemplateError) as exc_info:
        parse_cases(_template(tests_yaml))
    assert message in str(exc_info.value)


def test_a_contains_path_that_is_not_a_string_is_a_failure():
    template = _template(
        """
        tests:
          - name: x
            vars: {subject: a}
            contains: {steps: "3", nowhere: a}
        """
    )
    (result,) = run_tests(template)
    assert result.failures == [
        "steps: not a string in the rendered params, cannot check contains",
        "nowhere: not a string in the rendered params, cannot check contains",
    ]


def test_an_alias_bomb_in_tests_is_refused_at_load_time():
    bomb = "tests:\n  - &a [*a]\n"
    with pytest.raises(TemplateError):
        load_template_str(BASE + bomb)


# --- CLI ---------------------------------------------------------------------


def _cli(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["ptm", *argv])
    cli.main()


def test_cli_runs_the_example_and_exits_zero(monkeypatch, capsys):
    _cli(monkeypatch, "test", str(EXAMPLE))
    out = capsys.readouterr().out
    assert out.count("  PASS  ") == 3
    assert "3 passed, 0 failed" in out


def test_cli_reports_failures_and_exits_one(tmp_path, monkeypatch, capsys):
    path = tmp_path / "t.yaml"
    path.write_text(
        BASE + "tests:\n  - {name: off by one, vars: {subject: a}, expect: {steps: 29}}\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit) as exc_info:
        _cli(monkeypatch, "test", str(path))
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "  FAIL  off by one" in out and "steps: expected 29, got 30" in out
    assert "0 passed, 1 failed" in out


def test_cli_templates_without_tests_pass_unless_required(tmp_path, monkeypatch, capsys):
    path = tmp_path / "plain.yaml"
    path.write_text(BASE, encoding="utf-8")
    _cli(monkeypatch, "test", str(path))
    assert "no tests" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc_info:
        _cli(monkeypatch, "test", str(path), "--require-tests")
    assert exc_info.value.code == 1


def test_cli_validate_rejects_a_malformed_tests_list(tmp_path, monkeypatch, capsys):
    path = tmp_path / "bad.yaml"
    path.write_text(BASE + "tests: [{name: x, vars: {subject: a}}]\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        _cli(monkeypatch, "validate", str(path))
    assert exc_info.value.code == 1
    assert "has no assertion" in capsys.readouterr().err


def test_cli_test_marks_an_invalid_file_and_keeps_going(tmp_path, monkeypatch, capsys):
    broken = tmp_path / "broken.yaml"
    broken.write_text("name: [", encoding="utf-8")
    with pytest.raises(SystemExit):
        _cli(monkeypatch, "test", str(broken), str(EXAMPLE))
    captured = capsys.readouterr()
    assert "INVALID:" in captured.err
    assert "3 passed, 0 failed, 1 invalid" in captured.out
