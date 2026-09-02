from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from prompt_template_manager.cli import main

VALID_YAML = """
name: greet
version: "1"
capability: echo
params:
  message: "hello, {{ who }}!"
variables:
  who:
    type: string
    default: world
"""

BAD_YAML = """
name: broken
version: "1"
capability: echo
params:
  a: "{{ never_declared }}"
"""


@pytest.fixture
def template_file(tmp_path: Path) -> Path:
    path = tmp_path / "greet.yaml"
    path.write_text(VALID_YAML)
    return path


def _run(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["ptm", *argv])
    main()


def test_validate_ok(monkeypatch, capsys, template_file):
    _run(monkeypatch, ["validate", str(template_file)])
    out = capsys.readouterr().out
    assert "OK: greet v1" in out


def test_validate_reports_undeclared_reference_and_exits_nonzero(monkeypatch, capsys, tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text(BAD_YAML)
    with pytest.raises(SystemExit) as exc_info:
        _run(monkeypatch, ["validate", str(path)])
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "INVALID" in err
    assert "never_declared" in err


def test_render_default(monkeypatch, capsys, template_file):
    _run(monkeypatch, ["render", str(template_file)])
    out = capsys.readouterr().out
    assert json.loads(out) == {"message": "hello, world!"}


def test_render_with_var_override(monkeypatch, capsys, template_file):
    _run(monkeypatch, ["render", str(template_file), "--var", "who=Ada", "--pretty"])
    out = capsys.readouterr().out
    assert json.loads(out) == {"message": "hello, Ada!"}
    assert "\n" in out  # --pretty indents, so the output spans multiple lines


def test_render_missing_required_var_exits_nonzero(monkeypatch, capsys, tmp_path):
    path = tmp_path / "req.yaml"
    path.write_text(
        """
name: x
version: "1"
capability: echo
params:
  a: "{{ needed }}"
variables:
  needed:
    type: string
    required: true
"""
    )
    with pytest.raises(SystemExit) as exc_info:
        _run(monkeypatch, ["render", str(path)])
    assert exc_info.value.code == 1
    assert "missing required variable" in capsys.readouterr().err


def test_info_lists_variables(monkeypatch, capsys, template_file):
    _run(monkeypatch, ["info", str(template_file)])
    out = capsys.readouterr().out
    assert "greet" in out
    assert "who: string, default='world'" in out


def test_validate_multiple_templates_reports_summary_and_exit_code(monkeypatch, capsys, tmp_path):
    good = tmp_path / "good.yaml"
    good.write_text(VALID_YAML)
    bad = tmp_path / "bad.yaml"
    bad.write_text(BAD_YAML)

    with pytest.raises(SystemExit) as exc_info:
        _run(monkeypatch, ["validate", str(good), str(bad)])
    assert exc_info.value.code == 1

    out = capsys.readouterr()
    assert "OK: greet v1" in out.out
    assert "1 valid, 1 invalid" in out.out
    assert "INVALID" in out.err
    assert str(bad) in out.err


def test_validate_multiple_valid_templates_exits_zero(monkeypatch, capsys, tmp_path):
    first = tmp_path / "a.yaml"
    first.write_text(VALID_YAML)
    second = tmp_path / "b.yaml"
    second.write_text(VALID_YAML)

    _run(monkeypatch, ["validate", str(first), str(second)])
    out = capsys.readouterr().out
    assert "2 valid, 0 invalid" in out


def test_render_with_vars_file(monkeypatch, capsys, tmp_path):
    template_path = tmp_path / "greet.yaml"
    template_path.write_text(VALID_YAML)
    vars_file = tmp_path / "vars.yaml"
    vars_file.write_text("who: Grace\n")

    _run(monkeypatch, ["render", str(template_path), "--vars-file", str(vars_file)])
    out = capsys.readouterr().out
    assert json.loads(out) == {"message": "hello, Grace!"}


def test_render_var_flag_overrides_vars_file(monkeypatch, capsys, tmp_path):
    template_path = tmp_path / "greet.yaml"
    template_path.write_text(VALID_YAML)
    vars_file = tmp_path / "vars.yaml"
    vars_file.write_text("who: Grace\n")

    _run(
        monkeypatch,
        ["render", str(template_path), "--vars-file", str(vars_file), "--var", "who=Ada"],
    )
    out = capsys.readouterr().out
    assert json.loads(out) == {"message": "hello, Ada!"}


def test_render_missing_vars_file_exits_nonzero(monkeypatch, capsys, template_file, tmp_path):
    with pytest.raises(SystemExit) as exc_info:
        _run(
            monkeypatch,
            ["render", str(template_file), "--vars-file", str(tmp_path / "nope.yaml")],
        )
    assert exc_info.value.code == 1
    assert "no such vars file" in capsys.readouterr().err


def test_submit_happy_path(monkeypatch, capsys, template_file):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"id": "j1", "polling_url": "/v1/jobs/j1"})
        return httpx.Response(200, json={"status": "ready", "result": {"echoed": True}})

    import prompt_template_manager.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "submit_and_wait",
        lambda gateway_url, capability, params, timeout=60.0: {"echoed": True},
    )

    _run(monkeypatch, ["submit", str(template_file), "--gateway-url", "http://gateway.test"])
    out = capsys.readouterr().out
    assert json.loads(out) == {"echoed": True}
