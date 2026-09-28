# AgentKernel 里程碑文档

本目录用于管理 `AgentKernel` 个人项目的背景说明、技术边界和 3 阶段里程碑计划。

项目中文名：Agent 内核
项目英文名：AgentKernel

## 项目背景

市面上做 Agent 应用，大多直接套 LangChain、Claude Agent SDK 这类框架，主循环、工具调用、上下文管理全被框架封装。这样虽然快，但面试被问到「ReAct 怎么实现、工具调用失败怎么处理、上下文太长怎么办」时，只能答「框架帮我做了」。

本项目反过来：围绕实习项目中由 Claude Agent SDK 封装的能力，用 Python **先复现一个可解释的 Runtime 基线，再针对具体问题做优化实验**，并配套一个使用 MySQL 持久化的检索模块。项目包含 ReAct 主循环、工具调用契约、参数校验、非法 JSON 修复、上下文策略、MCP 协议、增量索引和混合检索，但不复制 Workbench 的 Web、业务 Agent 和企业治理层。

目标不是「再造一个 OpenClaw」，而是验证原理级工程能力——实习「会用」框架搭平台，个人项目「能理解并验证」内核机制。

更完整的背景说明见：[project-background.md](./project-background.md)；硬边界见：[technical-scope-and-boundary.md](./technical-scope-and-boundary.md)。

## 当前进度

- M1（ReAct 内核）✅ 已实现
- M2（MCP 协议与示例工具链）✅ 已实现
- M3（交付物）✅ 已完成（录屏可选）：`eval.py`、README、架构图、演示脚本、简历与面试材料均已就绪

## 与实习项目 AI Agent Workbench 互补

实习项目直接使用 Claude Agent SDK「会用」框架搭业务工作台；本项目围绕实习中遇到的 Runtime、Tool Calling 和 MCP 能力「复现基线、发现问题、优化实现、验证效果」。两者不是两个同类产品：Workbench 负责用户、业务和治理，AgentKernel 负责解释、改进和验证框架底层机制。详见 [README 边界声明](../README.md#边界声明) 和 [技术边界](./technical-scope-and-boundary.md)。

## 里程碑时间轴

- 项目开始时间：`2026-08-29`
- 项目结束时间：`2026-09-25`
- 项目周期：4 周（3 周理想值，按 4 周排）
- M1：`2026-08-29 ~ 2026-09-08`
- M2：`2026-09-09 ~ 2026-09-18`
- M3：`2026-09-19 ~ 2026-09-25`

## 文档索引

**核心说明**

1. [项目背景说明](./project-background.md)
2. [技术选型与边界说明](./technical-scope-and-boundary.md)

**阶段技术说明**

3. [里程碑 1：ReAct 内核可跑](./milestone-1-kernel.md)
4. [里程碑 2：MCP 协议与示例工具链打通](./milestone-2-mcp.md)
5. [里程碑 3：交付物与缓冲](./milestone-3-deliverables.md)

**研究补充材料（Addendum）**

6. [教学映射（agent-study ↔ OpenClaw ↔ Workbench）](./Addendum/learning-map.md)
7. [自我审查报告（Claude SDK / 高星 MCP 库 / agent-study）](./Addendum/self-review.md)
8. [ADR-001：MySQL 主存储](./Addendum/adr-001-mysql-primary-storage.md)
9. [框架对比：DeepSeek Harness 与 AgentKernel](./Addendum/framework-comparison-deepseek-harness.md)
10. [演示脚本](./Addendum/demo-script.md)
11. [简历与面试材料](./Addendum/resume-and-interview.md)

**架构图与面试蓝图**

11. [架构图源文件](./architecture.mmd)
12. [架构图 PNG](./architecture.png)
13. [面试蓝图 HTML](./agentkernel-interview-blueprint.html)

## 工作节奏说明

本项目按个人学习节奏设计，每天 2-3 个 45min 块。每个里程碑一条主线，不追求平台化扩展。

每个里程碑的验收控制在半天内，内容包括：

1. 功能演示。
2. 代码走读。
3. 遗留问题确认。
4. 下一阶段任务确认。

如果某个功能明显超出当前里程碑投入能力，优先降级为 mock、样例或文档说明，不扩大为实现范围。

## 最终成果目标

项目结束时应具备：

1. 一个可运行的 CLI Runtime 演示（多轮对话 + 工具调用）。
2. 可测试的 Tool Calling 契约、JSON 修复和上下文管理策略。
3. MCP stdio/JSON-RPC client/server 的协议级测试。
4. MySQL 文档库和检索模块作为实验样例，验证 Runtime 如何接入主流数据库持久化外部状态并保留工具结果来源。
5. `eval.py`、README、架构图、演示脚本和简历描述（录屏可选），能清楚说明与 Workbench 的边界。
