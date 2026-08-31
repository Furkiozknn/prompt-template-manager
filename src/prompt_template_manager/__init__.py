"""prompt-template-manager: versioned, git-diffable prompt/pipeline templates.

Public surface::

    from prompt_template_manager import (
        Template, VariableSpec, TemplateError,
        load_template_file, load_template_str,
        render_template, resolve_variables, validate_template,
    )
"""

from __future__ import annotations

from .loader import load_template_file, load_template_str
from .models import Template, TemplateError, VariableSpec
from .renderer import render_template, resolve_variables, validate_template

__all__ = [
    "Template",
    "VariableSpec",
    "TemplateError",
    "load_template_file",
    "load_template_str",
    "render_template",
    "resolve_variables",
    "validate_template",
]

__version__ = "0.1.0"
