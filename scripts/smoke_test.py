"""Pre-deploy smoke test for oncura-billing.

Same pattern as oncura-programs / oncura-apps:
  1. Every .py file parses as valid Python.
  2. Every core/ module imports cleanly with streamlit installed.
  3. Every `module.attr` reference in pages/*.py resolves.

Exit 0 = safe to push. Exit 1 = something will break on Cloud.
"""
from __future__ import annotations

import ast
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ONCURA_BILLING_LOCAL", "1")


def syntax_check(files):
    errors = []
    for f in files:
        try:
            ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError as e:
            errors.append(f"SYNTAX: {f.relative_to(ROOT)}: line {e.lineno}: {e.msg}")
    return errors


def import_core_modules():
    core_dir = ROOT / "core"
    modules, errors = {}, []
    for f in sorted(core_dir.glob("*.py")):
        if f.stem == "__init__":
            continue
        full = f"core.{f.stem}"
        try:
            modules[f.stem] = importlib.import_module(full)
        except Exception as e:
            errors.append(f"IMPORT: {full}: {type(e).__name__}: {e}")
    return modules, errors


def find_aliased_imports(tree):
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "core":
            for alias in node.names:
                out[alias.asname or alias.name] = alias.name
    return out


def check_page_references(page, core_modules):
    src = page.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(page))
    except SyntaxError:
        return []
    aliased = find_aliased_imports(tree)
    errors = []
    rel = page.relative_to(ROOT)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if not isinstance(node.value, ast.Name):
            continue
        if node.value.id not in aliased:
            continue
        mod_name = aliased[node.value.id]
        mod = core_modules.get(mod_name)
        if mod is None:
            errors.append(f"REF:    {rel}:{node.lineno}: core.{mod_name} not importable")
            continue
        if not hasattr(mod, node.attr):
            errors.append(
                f"MISSING:{rel}:{node.lineno}: core.{mod_name}.{node.attr} does not exist"
            )
    return errors


def main():
    print(f"Smoke test :: root={ROOT}")
    py_files = (
        [ROOT / "app.py"]
        + sorted((ROOT / "core").glob("*.py"))
        + sorted((ROOT / "pages").glob("*.py"))
    )
    py_files = [f for f in py_files if f.exists()]

    syn_errors = syntax_check(py_files)
    if syn_errors:
        print("\n".join(syn_errors))
        return 1
    print(f"  OK syntax ({len(py_files)} files)")

    core_modules, imp_errors = import_core_modules()
    if imp_errors:
        print("\n".join(imp_errors))
        return 1
    print(f"  OK core imports ({len(core_modules)} modules)")

    pages = sorted((ROOT / "pages").glob("*.py"))
    ref_errors = []
    for p in pages:
        ref_errors.extend(check_page_references(p, core_modules))
    if ref_errors:
        print("\n".join(ref_errors))
        return 1
    print(f"  OK references ({len(pages)} pages)")

    print("All checks passed - safe to push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
