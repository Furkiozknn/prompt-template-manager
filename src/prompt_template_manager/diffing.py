"""`ptm diff`: what changed between two versions of a template, and for whom.

``git diff`` shows which lines of the YAML moved. It does not say whether
the change breaks the people who call the template. Langfuse and similar
registries answer that with numbered versions and labels on a server; here
the versions are files in git, so the answer is a semantic diff:

- **breaking**: a caller has to change what they pass. A variable was
  removed (passing it is now an "unknown variable" error), a variable became
  required or was added as required, a type changed, the capability changed
  (the request goes to a different endpoint).
- **output**: the same call now renders something different. A default
  changed, a param was added, removed or edited.
- **cosmetic**: nothing a caller or the model sees. Descriptions.

``--check-version`` turns that into a rule for CI: any breaking or output
change must come with a new ``version``, and when both versions are plain
numbers (``1``, ``2.3``, ``1.4.0``) a breaking change must raise the first
one, the semver major.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .models import Template

BREAKING, OUTPUT, COSMETIC = "breaking", "output", "cosmetic"
_KIND_ORDER = {BREAKING: 0, OUTPUT: 1, COSMETIC: 2}

_NUMERIC_VERSION = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


@dataclass
class Change:
    kind: str
    where: str
    message: str


@dataclass
class TemplateDiff:
    name: str
    old_version: str
    new_version: str
    changes: list[Change] = field(default_factory=list)

    def count(self, kind: str) -> int:
        return sum(1 for c in self.changes if c.kind == kind)

    def version_problem(self) -> Optional[str]:
        """Why the new version does not fit the changes, or None if it does."""
        relevant = self.count(BREAKING) + self.count(OUTPUT)
        if not relevant:
            return None
        if self.new_version == self.old_version:
            return (
                f"version is still {self.old_version!r} although {relevant} breaking/output "
                "change(s) were made; bump 'version'"
            )
        if self.count(BREAKING):
            old, new = _major(self.old_version), _major(self.new_version)
            if old is not None and new is not None and new <= old:
                return (
                    f"{self.count(BREAKING)} breaking change(s) need a new major version: "
                    f"{self.old_version!r} -> {self.new_version!r} keeps major {old}"
                )
        return None


def _major(version: str) -> Optional[int]:
    match = _NUMERIC_VERSION.match(version.strip())
    return int(match.group(1)) if match else None


def _show(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _word_diff(old: str, new: str) -> str:
    """``[-removed-]{+added+}`` inline, like ``git diff --word-diff``, with
    unchanged runs longer than a few words shortened to keep the line short."""
    a, b = old.split(" "), new.split(" ")
    pieces: list[str] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            same = a[i1:i2]
            if len(same) > 6:
                same = same[:2] + ["..."] + same[-2:]
            pieces.append(" ".join(same))
        else:
            if i2 > i1:
                pieces.append("[-" + " ".join(a[i1:i2]) + "-]")
            if j2 > j1:
                pieces.append("{+" + " ".join(b[j1:j2]) + "+}")
    return " ".join(p for p in pieces if p)


def _diff_params(old: Any, new: Any, path: str, out: list[Change]) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() - new.keys(), key=str):
            out.append(Change(OUTPUT, f"{path}.{key}", f"param removed (was {_show(old[key])})"))
        for key in sorted(new.keys() - old.keys(), key=str):
            out.append(Change(OUTPUT, f"{path}.{key}", f"param added: {_show(new[key])}"))
        for key in sorted(old.keys() & new.keys(), key=str):
            _diff_params(old[key], new[key], f"{path}.{key}", out)
        return
    if type(old) is type(new) and old == new:
        return
    if isinstance(old, str) and isinstance(new, str):
        out.append(Change(OUTPUT, path, _word_diff(old, new)))
    else:
        out.append(Change(OUTPUT, path, f"{_show(old)} -> {_show(new)}"))


def diff_templates(old: Template, new: Template) -> TemplateDiff:
    """Every change from ``old`` to ``new``, classified, breaking first."""
    result = TemplateDiff(name=new.name, old_version=old.version, new_version=new.version)
    changes = result.changes

    if old.name != new.name:
        changes.append(Change(COSMETIC, "name", f"{old.name!r} -> {new.name!r}"))
    if old.capability != new.capability:
        changes.append(
            Change(BREAKING, "capability", f"{old.capability!r} -> {new.capability!r} (a different endpoint)")
        )
    if old.description != new.description:
        changes.append(Change(COSMETIC, "description", "changed"))

    for name in sorted(old.variables.keys() - new.variables.keys()):
        changes.append(
            Change(BREAKING, f"variables.{name}", "removed (a caller still passing it gets 'unknown variable')")
        )
    for name in sorted(new.variables.keys() - old.variables.keys()):
        spec = new.variables[name]
        if spec.required:
            changes.append(Change(BREAKING, f"variables.{name}", f"added as required ({spec.type})"))
        else:
            default = "" if spec.default is None else f", default {_show(spec.default)}"
            changes.append(Change(OUTPUT, f"variables.{name}", f"added as optional ({spec.type}{default})"))
    for name in sorted(old.variables.keys() & new.variables.keys()):
        before, after = old.variables[name], new.variables[name]
        where = f"variables.{name}"
        if before.type != after.type:
            changes.append(Change(BREAKING, where, f"type {before.type} -> {after.type}"))
        if not before.required and after.required:
            changes.append(Change(BREAKING, where, "now required"))
        elif before.required and not after.required:
            changes.append(Change(OUTPUT, where, "no longer required"))
        if before.default != after.default or type(before.default) is not type(after.default):
            changes.append(Change(OUTPUT, where, f"default {_show(before.default)} -> {_show(after.default)}"))
        if before.description != after.description:
            changes.append(Change(COSMETIC, where, "description changed"))

    _diff_params(old.params, new.params, "params", changes)
    changes.sort(key=lambda c: _KIND_ORDER[c.kind])
    return result


def format_diff(diff: TemplateDiff) -> str:
    version = (
        f"v{diff.old_version}" if diff.old_version == diff.new_version else f"v{diff.old_version} -> v{diff.new_version}"
    )
    lines = [f"{diff.name}: {version}"]
    if not diff.changes:
        lines.append("  no changes")
    width = max((len(c.kind) for c in diff.changes), default=0)
    for change in diff.changes:
        label = change.kind.upper() if change.kind == BREAKING else change.kind
        lines.append(f"  {label.ljust(width)}  {change.where}: {change.message}")
    lines.append(
        f"{diff.count(BREAKING)} breaking, {diff.count(OUTPUT)} output, {diff.count(COSMETIC)} cosmetic change(s)"
    )
    return "\n".join(lines)


def diff_as_dict(diff: TemplateDiff) -> dict[str, Any]:
    return {
        "name": diff.name,
        "old_version": diff.old_version,
        "new_version": diff.new_version,
        "counts": {kind: diff.count(kind) for kind in (BREAKING, OUTPUT, COSMETIC)},
        "changes": [{"kind": c.kind, "where": c.where, "message": c.message} for c in diff.changes],
        "version_problem": diff.version_problem(),
    }
