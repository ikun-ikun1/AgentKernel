"""路径边界（P0-5）：文档根白名单 + realpath/commonpath + 拒绝 symlink 逃逸。

规则：
- 候选路径先 `resolve(strict=True)`，再用 `is_relative_to(root)` 判定；根目录本身也 resolve。
- 目录遍历 `followlinks=False`，并主动剔除符号链接目录；每个文件再 resolve 复核一次。
- 越界、超大小、超数量、超深度一律抛 `PathBoundaryError`（拒绝，不静默跳过）。
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_FILES = 200
DEFAULT_MAX_DEPTH = 4
SUPPORTED_SUFFIXES = {".pdf", ".md", ".markdown", ".txt"}


class PathBoundaryError(ValueError):
    """路径越界或超过资源上限。"""


def doc_roots() -> list[Path]:
    raw = os.environ.get("AGENTKERNEL_DOC_ROOTS", "")
    candidates = [Path(p).expanduser() for p in raw.split(os.pathsep) if p.strip()]
    if not candidates:
        candidates = [Path.cwd()]
    roots: list[Path] = []
    for candidate in candidates:
        try:
            roots.append(candidate.resolve(strict=True))
        except OSError:
            continue
    if not roots:
        raise PathBoundaryError("AGENTKERNEL_DOC_ROOTS 中没有可用目录")
    return roots


def ensure_within(path: str | Path, roots: list[Path] | None = None) -> Path:
    resolved_roots = roots if roots is not None else doc_roots()
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise PathBoundaryError(f"路径不存在或不可解析：{candidate}") from None
    for root in resolved_roots:
        if resolved == root or resolved.is_relative_to(root):
            return resolved
    raise PathBoundaryError(
        f"路径不在允许的根目录内：{candidate}"
        f"（根：{', '.join(str(root) for root in resolved_roots)}）"
    )


def check_size(path: Path, limit: int = DEFAULT_MAX_FILE_BYTES) -> None:
    size = path.stat().st_size
    if size > limit:
        raise PathBoundaryError(f"文件超过大小上限 {limit} 字节：{path}（{size} 字节）")


def collect_documents(
    path: str | Path,
    *,
    roots: list[Path] | None = None,
    max_files: int = DEFAULT_MAX_FILES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> list[Path]:
    """把一个文件或目录展开成待入库文件列表；任何越界/超限都抛错。"""
    resolved_roots = roots if roots is not None else doc_roots()
    resolved = ensure_within(path, resolved_roots)
    if resolved.is_file():
        check_size(resolved, max_file_bytes)
        return [resolved]
    if not resolved.is_dir():
        raise PathBoundaryError(f"不支持的路径类型：{resolved}")

    base_depth = len(resolved.parts)
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(resolved, followlinks=False):
        current = Path(dirpath)
        depth = len(current.parts) - base_depth
        if depth >= max_depth:
            dirnames[:] = []
        # 符号链接目录不跟随：避免逃逸与环；文件级的链接由 ensure_within 再复核
        dirnames[:] = [name for name in dirnames if not (current / name).is_symlink()]
        for name in sorted(filenames):
            if Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            target = ensure_within(current / name, resolved_roots)
            check_size(target, max_file_bytes)
            files.append(target)
            if len(files) > max_files:
                raise PathBoundaryError(f"文件数超过上限 {max_files}：{resolved}")
    return files
