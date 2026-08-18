# 阶段 1：内核可跑（第 1 周）

> 目标：**CLI 多轮对话 + 能调 2 个内置工具 + 坏 JSON 不崩**。
> 优先级：🔴 底线（全做）｜ 每天 2-3 个 45min 块。

---

## 验收标准（本阶段完成的定义）

- [ ] CLI 能多轮对话，不崩
- [ ] 能调 2 个内置工具（当前时间 / 计算器）
- [ ] 故意给非法 JSON，能修复或降级，不崩

---

## 前置准备（开写前确认）

- [ ] DeepSeek API Key 已申请，能调通一次
- [ ] Python 3.11+ 环境就绪
- [ ] 通读 agent-study Ch3（ReAct）、Ch11（Tool Calling）
- [ ] 通读 OpenClaw `tool-call-repair` 源码（半天，3 行笔记）

---

## D1-2：项目骨架 + `llm.py` + 最小 ReAct 循环 🔴

**目标**：不调工具，先跑通一次对话。

- [ ] 建目录结构、`.gitignore`、`.env.example`
- [ ] `llm.py`：`chat(messages) -> str`，接 DeepSeek
- [ ] `agent.py`：最小 ReAct 循环（只有「思考 → 最终回答」，还没工具）
- [ ] CLI 入口：读一行输入，回一行输出

**验收**：`python -m agentkernel` 能一问一答。

**踩坑提示**：
- API Key 放 `.env`，用 python-dotenv 读，别硬编码进代码
- DeepSeek base_url：`https://api.deepseek.com`

---

## D3-4：工具注册 + 2 个内置工具 + CLI 交互 🔴

**目标**：Agent 能调工具。

- [ ] `tools/registry.py`：工具注册表，支持「名称/描述/参数 schema」
- [ ] 2 个内置工具：`get_current_time`（当前时间）、`calculator`（计算器）
- [ ] 工具描述注入 system prompt，让模型知道有哪些工具
- [ ] 解析模型输出的 `{"action": ..., "action_input": ...}`

**验收**：问「现在几点」「帮我算 123*456」，Agent 调工具回答。

**踩坑提示**：
- 工具描述要写清「什么时候用、参数是什么」，模型才选得对
- 参数校验：模型可能传错参数类型，registry 里要兜住

---

## D5-7：非法 JSON 修复 + SQLite 记忆 + 边界 🔴

**目标**：抗造——坏输入不崩、重启不丢。

- [ ] `tools/json_repair.py`：三层修复（正则提取 → JSON 修复 → 降级纯文本）
- [ ] `memory/sqlite_store.py`：会话 + 消息的持久化，多轮对话上下文不丢
- [ ] 边界处理：超长上下文截断、工具执行报错回灌

**验收**：
- [ ] 故意让模型输出带废话的 JSON → 能修复
- [ ] 重启后接着上一轮对话 → 还记得上下文
- [ ] 工具报错（如计算器除 0）→ 不崩，错误回灌让模型重试

**踩坑提示**：
- JSON 修复先处理「提取」，再处理「修复」，别混在一个函数里
- 工具执行用 try/except 包住，错误信息转成「观察」回灌

---

## 本阶段产出

- [ ] 可跑的 CLI Agent（多轮 + 工具 + 抗造）
- [ ] `llm.py` / `agent.py` / `tools/registry.py` / `tools/json_repair.py` / `memory/sqlite_store.py`

## 卡壳 2 小时法则

> 一个东西搞 2 小时没通 → 停下来问小爪，或先跳过做别的，不硬扛。
