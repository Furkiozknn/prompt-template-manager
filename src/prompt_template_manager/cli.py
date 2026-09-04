"""Command-line entry point: `ptm validate|render|info|submit`."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .gateway_client import GatewayJobFailedError, GatewayJobTimeoutError, GatewaySubmissionError, submit_and_wait
from .loader import load_template_file, load_vars_file
from .models import TemplateError
from .renderer import render_template, validate_template


def _parse_var_args(pairs: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--var must be KEY=VALUE, got {pair!r}")
        key, _, value = pair.partition("=")
        result[key] = value
    return result


def _cmd_validate(args: argparse.Namespace) -> None:
    ok_count = 0
    invalid_count = 0
    for path in args.templates:
        try:
            template = load_template_file(path)
            warnings = validate_template(template)
        except TemplateError as exc:
            print(f"INVALID: {path}: {exc}", file=sys.stderr)
            invalid_count += 1
            continue

        print(f"OK: {template.name} v{template.version} ({path})")
        for warning in warnings:
            print(f"  warning: {warning}")
        ok_count += 1

    if len(args.templates) > 1:
        print(f"\n{ok_count} valid, {invalid_count} invalid")

    if invalid_count:
        raise SystemExit(1)


def _resolve_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """CLI `--var KEY=VALUE` flags, layered on top of an optional
    `--vars-file` -- `--var` always wins on a name given both ways."""
    overrides = _parse_var_args(args.var)
    if getattr(args, "vars_file", None):
        try:
            file_vars = load_vars_file(args.vars_file)
        except TemplateError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        overrides = {**file_vars, **overrides}
    return overrides


def _cmd_render(args: argparse.Namespace) -> None:
    overrides = _resolve_overrides(args)
    try:
        template = load_template_file(args.template)
        rendered = render_template(template, overrides)
    except TemplateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    indent = 2 if args.pretty else None
    print(json.dumps(rendered, indent=indent))


def _cmd_info(args: argparse.Namespace) -> None:
    try:
        template = load_template_file(args.template)
    except TemplateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    print(f"{template.name}  (v{template.version})")
    if template.description:
        print(f"  {template.description}")
    print(f"  capability: {template.capability}")
    if not template.variables:
        print("  variables: (none)")
    else:
        print("  variables:")
        for name, spec in template.variables.items():
            bits = [spec.type]
            if spec.required:
                bits.append("required")
            elif spec.default is not None:
                bits.append(f"default={spec.default!r}")
            desc = f" - {spec.description}" if spec.description else ""
            print(f"    {name}: {', '.join(bits)}{desc}")


def _cmd_submit(args: argparse.Namespace) -> None:
    overrides = _resolve_overrides(args)
    try:
        template = load_template_file(args.template)
        rendered = render_template(template, overrides)
    except TemplateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    try:
        result: dict[str, Any] = submit_and_wait(
            args.gateway_url, template.capability, rendered, timeout=args.timeout
        )
    except (GatewaySubmissionError, GatewayJobFailedError, GatewayJobTimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="ptm", description="prompt-template-manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate", help="check one or more templates for structural problems"
    )
    validate_parser.add_argument(
        "templates", nargs="+", metavar="TEMPLATE", help="one or more template files (shell globs work, e.g. templates/*.yaml)"
    )
    validate_parser.set_defaults(func=_cmd_validate)

    render_parser = subparsers.add_parser("render", help="render a template to a concrete params JSON object")
    render_parser.add_argument("template")
    render_parser.add_argument("--var", action="append", default=[], help="KEY=VALUE, repeatable")
    render_parser.add_argument(
        "--vars-file", help="JSON or YAML file of variable name -> value; --var overrides take precedence"
    )
    render_parser.add_argument("--pretty", action="store_true", help="pretty-print the JSON output")
    render_parser.set_defaults(func=_cmd_render)

    info_parser = subparsers.add_parser("info", help="show a template's name, capability, and variables")
    info_parser.add_argument("template")
    info_parser.set_defaults(func=_cmd_info)

    submit_parser = subparsers.add_parser(
        "submit", help="render a template and submit it to an ai-job-gateway-compatible server"
    )
    submit_parser.add_argument("template")
    submit_parser.add_argument("--gateway-url", required=True)
    submit_parser.add_argument("--var", action="append", default=[], help="KEY=VALUE, repeatable")
    submit_parser.add_argument(
        "--vars-file", help="JSON or YAML file of variable name -> value; --var overrides take precedence"
    )
    submit_parser.add_argument("--timeout", type=float, default=60.0)
    submit_parser.set_defaults(func=_cmd_submit)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
