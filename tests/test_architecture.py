"""A6：分层依赖断言（AST，不引入 import-linter）。

规则：
- ports 不得依赖 adapters/cli/application；
- application 不得依赖 adapters/cli；
- adapters 不得依赖 cli；
- RAG 的纯模型/加载/分块模块不得依赖 adapters/cli；
- cli/main.py 不直接 import adapters（装配只在 cli/composition.py）。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "agentkernel"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _package_modules(package: str) -> list[Path]:
    return [p for p in (ROOT / package).rglob("*.py") if "__pycache__" not in p.parts]


def _violations(package: str, forbidden: set[str]) -> list[str]:
    bad: list[str] = []
    for path in _package_modules(package):
        for module in _imports(path):
            if any(module == item or module.startswith(item + ".") for item in forbidden):
                bad.append(f"{path.relative_to(ROOT)}: {module}")
    return bad


def test_ports_do_not_depend_on_outer_layers() -> None:
    bad = _violations(
        "ports", {"agentkernel.adapters", "agentkernel.cli", "agentkernel.application"}
    )
    assert bad == []


def test_application_does_not_depend_on_adapters_or_cli() -> None:
    bad = _violations("application", {"agentkernel.adapters", "agentkernel.cli"})
    assert bad == []


def test_adapters_do_not_depend_on_cli() -> None:
    assert _violations("adapters", {"agentkernel.cli"}) == []


def test_rag_core_is_free_of_adapters_and_cli() -> None:
    bad: list[str] = []
    for name in ("models.py", "loaders.py", "chunking.py"):
        path = ROOT / "rag" / name
        for module in _imports(path):
            if module.startswith(("agentkernel.adapters", "agentkernel.cli")):
                bad.append(f"{path.relative_to(ROOT)}: {module}")
    assert bad == []


def test_cli_main_does_not_import_adapters_directly() -> None:
    modules = _imports(ROOT / "cli" / "main.py")
    assert not [m for m in modules if m.startswith("agentkernel.adapters")]
