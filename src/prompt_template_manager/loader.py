"""Load a Template from a YAML file or string."""

from __future__ import annotations

from pathlib import Path

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


def load_template_file(path: str | Path) -> Template:
    path = Path(path)
    if not path.exists():
        raise TemplateError(f"no such file: {path}")
    return load_template_str(path.read_text(encoding="utf-8"), source_path=str(path))
