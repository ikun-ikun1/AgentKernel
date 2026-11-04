# 框架对比延伸：DeepSeek Harness（dsh）与 AgentKernel

> 来源：本地 `/home/ikun/dsh-handbook`、`/home/ikun/deepseek-harness-handbook`、`/home/ikun/dsh-research`（含官方包源码阅读笔记）。
> 目的：不重复造轮子，用「应用开发视角」对比生产级 Agent 框架（dsh）与教学型 Runtime（AgentKernel）的设计差异，面试时可讲。

## 1. 一句话对比

| | DeepSeek Harness（dsh） | AgentKernel |
|---|---|---|
| 定位 | 生产级「一切皆插件」Agent 框架 | 个人研究原型：解释 Runtime 底层 |
| 组装方式 | Profile / Bundle / Patch 声明式叠加 | 固定模块，代码内组装 |
| 主循环 | `dsh-agent` / `dsh-agent-loop`，可被插件扩展 | 手写 ReAct，固定不可插拔 |
| 会话 | JSONL 全量事件日志 + projection 投影（可回放/恢复/统计） | MySQL/SQLite 表：sessions/messages/tool_logs |
| 工具 | 插件提供，工具面动态组合，sandbox/权限策略按调用解析 | 固定 Registry，allowlist + JSON Schema 校验 |
| MCP | 作为工具/子代理生态接入 | 自行实现 wire protocol，用于验证底层 |

## 2. dsh 的核心机制（应用开发视角）

1. **一切皆插件**：CLI、Web UI、TUI、工具、session、LLM 适配器都是插件；核心只提供插件加载、会话、工具、LLM 等基础服务。
2. **Profile / Bundle / Patch 声明式组装**：`package.json` 的 `dsh.profile.bundles` + `cordis.patch.yml` 决定一个 profile 叠加哪些 bundle；换 profile 即换一组能力，不改代码。
3. **Cordis 插件基座**：`Context` 提供事件监听、命令注册、子插件；扩展点分通知事件和 waterfall 事件（如 `agent/request` 可动态修改 `reasoningEffort`，必须 `await next()`）。
4. **会话与投影**：session 以 JSONL 全量记录事件，再通过 projection 生成视图/统计；类似事件溯源，日志可恢复、可审计、可统计。
5. **DeepSeek 适配器**：`serialize.ts` 做协议转换、`translate.ts` 做 SSE 转换、`files-api.ts` 处理图片；推理链 `reasoning_content` 需原样回传，否则思考签名会丢。

## 3. 与 AgentKernel 的差异与收获

| 维度 | dsh | AgentKernel 学到什么 |
|------|-----|---------------------|
| 可扩展性 | 插件可插拔，扩展点标准化 | AgentKernel 固定 Runtime 是为了解释机制；生产化应走向扩展点/插件化 |
| 组装方式 | 声明式 Profile/Bundle | 固定代码组装简单可读，但不适合产品化 |
| 会话 | 事件日志 + projection | AgentKernel 用 SQL 表；理解了事件溯源在可回放/可审计上的优势 |
| 错误前提 | 适配器把「模型会犯错、网关会丢字段」当默认前提 | 与 AgentKernel 的 JSON 修复/allowlist/降级设计同源 |
| 安全 | sandbox 策略按调用解析 | AgentKernel 只做到 allowlist + 只读工具 |

**面试一句话**：完成独立实现的 Runtime 后，研读 DeepSeek Harness 的插件化架构，理解生产级框架如何用 Profile/Bundle 声明式组装能力、用事件日志会话支持恢复与审计，反观 AgentKernel 固定 Runtime 的教学定位——两者目标不同，但底层对「模型不可靠」的防御思路一致。

## 4. 与简历 bullet 的对应

简历中「框架对比延伸」一条可表述为：

> 完成独立实现的 Runtime 后，研读 DeepSeek Harness（dsh）插件化架构：Profile/Bundle 声明式组装、Cordis 扩展点、JSONL 会话投影与 DeepSeek 适配器推理链回传，对比 AgentKernel 固定 Runtime 的教学定位，理解生产级 Agent 框架的组装与容错设计。
