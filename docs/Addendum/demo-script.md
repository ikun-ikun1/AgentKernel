# AgentKernel 演示脚本

本脚本用于 M3 录屏和现场演示。完整演示约 3 分钟；没有 API Key 时可以只演示自动化验收和 RAG 检索。

## 0. 环境

```bash
cd /home/ikun/AgentKernel
source .venv/bin/activate
export HF_ENDPOINT=https://hf-mirror.com
```

向量模型已经下载并缓存后，可以去掉 `HF_ENDPOINT`。如果没有模型或不希望加载模型，使用 `--kb-backend lexical`，数据仍然持久化到 MySQL ngram 全文检索。

## 1. 自动化验收

```bash
python -m pytest -q
python eval.py
```

验收目标：默认测试用例全部通过；配置 `AGENTKERNEL_MYSQL_TEST_DSN` 后再执行 2 个 MySQL 集成测试；`python eval.py` mock 模式达到 `通过 5/5`。具体结果以本次执行输出为准。

这一步展示四类底层能力：

- ReAct 工具调用和观察回灌
- 非法 JSON 修复与降级
- 上下文保持
- MCP 工具链路

## 2. RAG 建库与增量更新

准备一个 Markdown 文件，例如 `demo-notes.md`，写入几段包含 `ReAct`、`MCP` 和 `AgentKernel` 的内容。

```bash
export AGENTKERNEL_KB_DSN=mysql+pymysql://agentkernel:agentkernel@127.0.0.1:3306/agentkernel
python -m agentkernel \
  --kb-backend hybrid \
  --docs ./demo-notes.md
```

启动时说明应包含：

```text
知识库：hybrid
```

如果向量依赖或模型不可用，系统应明确提示降级为 MySQL ngram 全文检索，而不是启动失败或丢失索引。

再次启动同一命令，文档 checksum 命中后不会重复重建 Chunk。修改文件后重新启动，只重建该文档的稳定 Chunk ID 和对应向量。

## 3. CLI 对话路径

在 CLI 中依次输入：

```text
你叫什么？
帮我算 123*456
什么是 ReAct？
/docs
/logs
```

讲解重点：

1. 计算器由 Registry 校验并执行，不是模型直接执行 Python。
2. ReAct 先产生工具调用，再把工具结果作为观察回灌给模型。
3. 知识库调用经过 MCP client/server，返回结果带文档来源。
4. `/logs` 展示的是 Runtime 工具观察审计，不是 Workbench 的企业审批审计系统。

## 4. MCP 独立链路

```bash
python -m agentkernel.mcp.server \
  --kb-db mysql+pymysql://agentkernel:agentkernel@127.0.0.1:3306/agentkernel \
  --backend lexical \
  ./demo-notes.md
```

另一个终端执行：

```bash
python -m agentkernel \
  --kb-db mysql+pymysql://agentkernel:agentkernel@127.0.0.1:3306/agentkernel \
  --mcp "python -m agentkernel.mcp.server --kb-db mysql+pymysql://agentkernel:agentkernel@127.0.0.1:3306/agentkernel ./demo-notes.md"
```

代码走读顺序：

1. `mcp/framing.py`：`Content-Length` 帧。
2. `mcp/client.py`：`initialize → tools/list → tools/call`。
3. `mcp/server.py`：JSON-RPC 错误映射和只读工具。
4. `rag/ingest.py`：文档 checksum、MySQL ngram、可选 Chroma 和 RRF；说明这是检索实验模块，不是业务知识库产品。

## 5. 录屏收尾

最后展示：

- `docs/architecture.png`
- `docs/project-background.md` 的互补边界
- `docs/technical-scope-and-boundary.md` 的明确不做项

录屏中不要把 AgentKernel 介绍成第二个 Workbench。应明确说：Workbench 负责直接使用 SDK 完成业务应用和治理，AgentKernel 负责对 Runtime、协议和检索接入机制做最小研究与验证。
