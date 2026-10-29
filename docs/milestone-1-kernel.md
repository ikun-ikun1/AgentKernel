# 里程碑 1：ReAct 内核可跑

> **历史文档（2026-09 里程碑快照）**：命令、测试数与进度为当时状态；当前状态与数字见 [status.md](./status.md)。

> **当前进度**：✅ 内核功能已实现。ReAct 循环、2 个内置工具、三层 JSON 修复、Runtime 记忆（MySQL 主存储，SQLite 测试适配器）、truncate/compact 上下文管理、LLM 客户端超时/重试/连接复用均已落地；`tests/` 覆盖 fake LLM 的主循环、上下文与工具审计用例。

## 周期与验收要求

- 周期：2026-08-29 ~ 2026-09-08（第 1 周）。
- 验收要求：9/08 前完成里程碑验收。
- 验收方式：功能演示 + 代码走读 + 本地启动检查。

## 阶段目标

完成最小可用内核，打通「CLI 输入 → ReAct 循环 → 调工具 → 输出回复」的主链路。

本阶段不追求知识库/MCP，重点是确认 ReAct 循环能稳定跑通、工具能调、坏输入不崩，并形成后续扩展的代码结构。

## 设计思路

本阶段先不做过早抽象。`runtime/agent.py` 只负责「思考 → 行动 → 观察 → 回复」循环，`runtime/llm.py` 屏蔽模型调用，`tools/registry.py` 管工具。

一次对话的数据流：

```
用户输入 → runtime/agent.py 组装上下文（system prompt + 工具描述 + 历史 + 输入）
        → runtime/llm.py 调 DeepSeek，返回 {"action": "...", "action_input": {...}}
        → 解析：工具调用 or final_answer？
           ├─ 工具调用 → registry 执行 → 观察结果写回历史 → 回到循环
           └─ final_answer → 输出给用户 → 结束
```

关键点：

1. MAX_STEPS 上限，防模型反复调工具死循环。
2. 工具执行结果（观察）回灌历史，让模型「看到」结果再决定下一步。
3. 工具报错 → 错误信息作为观察回灌，让模型重试，不崩。

## 模块与目的

1. `runtime/llm.py`  
目的：封装 DeepSeek 调用（OpenAI 兼容），统一 `chat(messages) -> str`，换模型只改 base_url。

2. `runtime/agent.py`  
目的：ReAct 主循环，编排思考/行动/观察/回复，带上下文管理。

3. `tools/contracts.py`  
目的：定义工具调用协议契约（合法 JSON 结构），registry 校验、json_repair 修复都依赖它。

4. `tools/registry.py`  
目的：工具注册表，管「名称/描述/参数 schema」，校验参数、执行、捕获异常。

5. `tools/json_repair.py`  
目的：非法 JSON 三层修复（正则提取 → JSON 修复 → 降级纯文本）。

6. `memory/sqlite_store.py`  
目的：会话 + 消息持久化，多轮对话上下文不丢。

## 交付物

1. 可运行的 CLI Agent（多轮 + 工具 + 抗造）。
2. `runtime/llm.py` / `runtime/agent.py` / `tools/contracts.py` / `tools/registry.py` / `tools/json_repair.py` / `memory/sqlite_store.py`。
3. 2 个内置工具：`get_current_time`（当前时间）、`calculator`（计算器）。
4. `.env.example` 和本地启动说明。

## 任务拆解

### D1-2：项目骨架 + `runtime/llm.py` + 最小 ReAct 循环

- 建目录结构、`.gitignore`、`.env.example`。
- `runtime/llm.py`：接 DeepSeek，跑通一次 `chat`。
- `runtime/agent.py`：最小 ReAct（只有「思考 → 最终回答」，还没工具）。
- CLI 入口：读一行输入，回一行输出。

### D3-4：工具注册 + 2 个内置工具 + CLI 交互

- `tools/registry.py`：工具注册表。
- 2 个内置工具（时间 / 计算器），描述注入 system prompt。
- 解析模型输出的 `{"action": ..., "action_input": ...}`。

### D5-7：非法 JSON 修复 + 记忆适配器 + 边界

- `tools/json_repair.py`：三层修复。
- `memory/sqlite_store.py`：会话 + 消息持久化。
- 边界：超长上下文截断、工具报错回灌。

## 验收标准

1. CLI 能多轮对话，不崩。
2. 能调 2 个内置工具（问「现在几点」「算 123*456」）。
3. 故意让模型输出带废话/残缺的 JSON，能修复或降级，不崩。
4. 重启后接着上一轮对话，还记得上下文。
5. 工具报错（如计算器除 0）不崩，错误回灌让模型重试。

## 明确不做

1. 不做知识库 RAG。
2. 不做 MCP 接入。
3. 不做复杂 Agent 配置解析。
4. 不做 Web 界面 / 登录 / 用户系统。
5. 不做生产级部署。

## 踩坑提示

- API Key 放 `.env`，别硬编码进代码。
- JSON 修复先「提取」再「修复」，别混在一个函数。
- 工具执行用 try/except 包住，错误信息转成「观察」回灌。
- 卡壳 2 小时 → 停下来问小爪，或先跳过做别的，不硬扛。
