"""兼容 shim 的弃用提示（v0.3.1）。

只用于旧 import 路径；内部代码不得依赖这些 shim。
"""

from __future__ import annotations

import warnings


def warn_deprecated(old: str, new: str) -> None:
    warnings.warn(
        f"{old} 已弃用，将在 v0.4.0 删除；请改用 {new}",
        DeprecationWarning,
        stacklevel=3,
    )
