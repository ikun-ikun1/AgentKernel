# 兼容 shim 迁移表（v0.3.1 → v0.4.0）

> v0.3.1 起旧 import 路径仍可用，但 import 时发 `DeprecationWarning`；**v0.4.0 删除**。
> 内部代码已清零旧路径，只有兼容测试还会 import 它们。

## 1. 路径映射

| 旧路径（v0.3.1 告警，v0.4.0 删除） | canonical 路径 |
|---|---|
| `agentkernel.memory.base` | `agentkernel.ports.runtime_store` |
| `agentkernel.memory.mysql_store` | `agentkernel.adapters.memory.mysql_store` |
| `agentkernel.memory.sqlite_store` | `agentkernel.adapters.memory.sqlite_store` |
| `agentkernel.runtime.llm` | `agentkernel.adapters.llm.openai_compatible` |
| `agentkernel.rag.ingest` | `agentkernel.rag.knowledge` / `agentkernel.rag.models` / `agentkernel.rag.loaders` / `agentkernel.rag.chunking` |
| `agentkernel.rag.mysql_store` | `agentkernel.adapters.knowledge.mysql_ngram` |
| `agentkernel.mcp.framing` | `agentkernel.protocol.mcp_framing` |
| `agentkernel.mcp.client` | `agentkernel.adapters.mcp.client` / `agentkernel.application.mcp_tools` |
| `agentkernel.mcp.server` | `agentkernel.adapters.mcp.knowledge_server` |

## 2. 典型替换

```python
# 旧
from agentkernel.memory.sqlite_store import SQLiteStore
from agentkernel.rag.ingest import KnowledgeBase, SearchResult
from agentkernel.mcp.client import register_mcp_tools

# 新
from agentkernel.adapters.memory.sqlite_store import SQLiteStore
from agentkernel.rag.knowledge import KnowledgeBase
from agentkernel.rag.models import SearchResult
from agentkernel.application.mcp_tools import register_mcp_tools
```

## 3. MCP server 入口

```bash
# v0.3.1 推荐（canonical）
python -m agentkernel.mcp_server --kb-db ~/.agentkernel/knowledge

# 旧入口仍可用但会告警；v0.4.0 删除
python -m agentkernel.mcp.server --kb-db ~/.agentkernel/knowledge
```

## 4. 兼容性测试

```bash
# 旧路径仍可 import + 有 DeprecationWarning；canonical 不告警
pytest -q tests/test_deprecated_shims.py
```

## 5. v0.4.0 删除清单

- `src/agentkernel/memory/{base,mysql_store,sqlite_store}.py`
- `src/agentkernel/runtime/llm.py`
- `src/agentkernel/rag/{ingest,mysql_store}.py`
- `src/agentkernel/mcp/{framing,client,server}.py`

删除前验收：`grep` 在 `src/`、`tests/`（兼容测试除外）、`eval.py`、`scripts/` 中不再命中旧路径；`make check` 绿；wheel 干净安装 + CLI smoke。
