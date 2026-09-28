"""Load a Template from a YAML file or string."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import Template, TemplateError


def load_template_str(text: str, *, source_path: str | None = None) -> Template:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise TemplateError(f"invalid YAML{f' in {source_path}' if source_path else ''}: {exc}") from exc
    if not isinstance(data, dict):
        raise TemplateError(
            f"template{f' ({source_path})' if source_path else ''} must be a YAML mapping at the top level"
        )
    return Template.from_dict(data, source_path=source_path)


def _read_text(path: Path, what: str) -> str:
    """Read a UTF-8 text file, turning every I/O failure into a TemplateError.

    A directory, an unreadable file or a binary file used to escape as a raw
    OSError / UnicodeDecodeError traceback - and in `ptm validate a b c` it
    aborted the whole run instead of marking one file INVALID.
    """
    if not path.exists():
        raise TemplateError(f"no such {what}: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise TemplateError(f"{what} {path} is not valid UTF-8 text: {exc.reason} at byte {exc.start}") from exc
    except OSError as exc:
        raise TemplateError(f"cannot read {what} {path}: {exc.strerror or exc}") from exc


def load_template_file(path: str | Path) -> Template:
    path = Path(path)
    return load_template_str(_read_text(path, "file"), source_path=str(path))


def load_vars_file(path: str | Path) -> dict[str, Any]:
    """Load a mapping of variable name -> value from a JSON or YAML file,
    for use with `ptm render --vars-file path`. Values still go through the
    same type coercion and validation as `--var` (which take precedence
    when both are given for the same name) -- this is purely a convenience
    for templates with more variables than are comfortable to type as
    repeated `--var KEY=VALUE` flags."""
    path = Path(path)
    text = _read_text(path, "vars file")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise TemplateError(f"invalid YAML/JSON in vars file {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise TemplateError(
            f"vars file {path} must contain a mapping of variable name -> value, "
            f"got {type(data).__name__}"
        )
    return data
