"""Nothing but `core.llm` may talk to the provider SDK.

The budget and the usage record live inside `core.llm.chat`. That guarantee is
only worth anything while `chat` is the single door to the provider - a module
that imported `openai` directly would walk straight past both.

A static check rather than an import-time assertion: this is a property of the
source, it costs nothing at runtime, and it fails in CI with the offending file
named rather than at some unlucky user's first request.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "career_copilot"

# The one module allowed to construct a provider client.
GATEWAY = PACKAGE_ROOT / "core" / "llm.py"

# Import roots that reach an LLM provider directly.
PROVIDER_ROOTS = {"openai", "anthropic", "mistralai", "google"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_only_the_gateway_imports_a_provider_sdk():
    offenders: dict[str, set[str]] = {}

    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path == GATEWAY:
            continue
        hits = _imported_roots(path) & PROVIDER_ROOTS
        if hits:
            offenders[str(path.relative_to(PACKAGE_ROOT.parent))] = hits

    assert not offenders, (
        "these modules reach the provider directly and so bypass the budget "
        f"and the usage record: {offenders}. Route the call through "
        "career_copilot.core.llm.chat instead."
    )


def test_the_gateway_itself_still_imports_one():
    """Guards the guard: a typo in PROVIDER_ROOTS would make this suite vacuous."""
    assert _imported_roots(GATEWAY) & PROVIDER_ROOTS
