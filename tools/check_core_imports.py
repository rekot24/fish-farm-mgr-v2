"""
tools/check_core_imports.py

Static check of the core/UI boundary: the shared core (bot/, capture/, detection/, config/)
runs on both the Windows GUI and the Linux headless server, so no core module may import
tkinter, ui, ctypes, winreg or tools.usb_pnp at module level (class bodies count, they run at
import time). Imports inside a function body (lazy imports) and inside `if TYPE_CHECKING:`
blocks are allowed.

Nothing is imported or executed from the files checked; they are only parsed.

Run from anywhere:
    python tools/check_core_imports.py
Exit code 0 = clean, 1 = violations found (each one is logged with file:line).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Allow `python tools/check_core_imports.py` (script dir, not repo root, is on sys.path).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bot import app_logger  # noqa: E402
from config.constants import (  # noqa: E402
    CORE_FORBIDDEN_DOTTED_MODULE,
    CORE_FORBIDDEN_ROOT_MODULES,
    CORE_PACKAGES,
)

_FORBIDDEN_PACKAGE, _FORBIDDEN_LEAF = CORE_FORBIDDEN_DOTTED_MODULE.rsplit(".", 1)


def _is_type_checking_guard(node: ast.If) -> bool:
    """True for `if TYPE_CHECKING:` / `if typing.TYPE_CHECKING:` (never runs at runtime)."""
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _forbidden_names(node: ast.stmt) -> list[str]:
    """
    Return the forbidden module names imported by one import statement (empty if none).
    Handles `import x.y`, `from x import y` and `from tools import usb_pnp`; relative
    imports stay inside the core package and are ignored.
    """
    found: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in CORE_FORBIDDEN_ROOT_MODULES or (
                    alias.name == CORE_FORBIDDEN_DOTTED_MODULE
                    or alias.name.startswith(CORE_FORBIDDEN_DOTTED_MODULE + ".")):
                found.append(alias.name)
    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        root = node.module.split(".")[0]
        if root in CORE_FORBIDDEN_ROOT_MODULES:
            found.append(node.module)
        elif (node.module == CORE_FORBIDDEN_DOTTED_MODULE
              or node.module.startswith(CORE_FORBIDDEN_DOTTED_MODULE + ".")):
            found.append(node.module)
        elif node.module == _FORBIDDEN_PACKAGE:
            found.extend(f"{node.module}.{a.name}" for a in node.names
                         if a.name == _FORBIDDEN_LEAF)
    return found


def _module_level_violations(statements: list[ast.stmt]) -> list[tuple[int, str]]:
    """
    Walk statements that execute at import time (module body, plus the bodies of module-level
    if/try/with/for/while and class bodies) and return (line, module) for each forbidden
    import. Does not descend into function bodies, or into `if TYPE_CHECKING:` blocks.
    """
    violations: list[tuple[int, str]] = []
    for node in statements:
        for name in _forbidden_names(node):
            violations.append((node.lineno, name))
        if isinstance(node, ast.If):
            if not _is_type_checking_guard(node):
                violations += _module_level_violations(node.body)
            violations += _module_level_violations(node.orelse)
        elif isinstance(node, ast.Try):
            blocks = [node.body, node.orelse, node.finalbody]
            blocks += [h.body for h in node.handlers]
            for block in blocks:
                violations += _module_level_violations(block)
        elif isinstance(node, (ast.With, ast.For, ast.While, ast.ClassDef)):
            # A class body runs at import time, so it counts as module level.
            violations += _module_level_violations(node.body)
    return violations


def check_core(root: Path) -> list[str]:
    """
    Parse every .py file under the core packages beneath `root` and return one
    "path:line: imports <module>" message per violation (empty list = clean).
    """
    messages: list[str] = []
    for package in CORE_PACKAGES:
        for path in sorted((root / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for line, name in _module_level_violations(tree.body):
                rel = path.relative_to(root).as_posix()
                messages.append(f"{rel}:{line}: imports {name} at module level")
    return messages


def main() -> int:
    """Check the repo this file lives in; log each violation and return the exit code."""
    messages = check_core(_PROJECT_ROOT)
    if messages:
        for message in messages:
            app_logger.log(message, "ERROR")
        app_logger.log(f"Core import check FAILED: {len(messages)} violation(s)", "ERROR")
        return 1
    app_logger.log("Core import check passed: core is free of UI and Windows-only imports", "INFO")
    return 0


if __name__ == "__main__":
    sys.exit(main())
