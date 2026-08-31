# ADR-001：使用 MySQL 8 作为主存储

## 状态

Accepted，待代码迁移与集成测试完成

## 背景

AgentKernel 早期使用 SQLite 是为了快速验证 Agent Runtime 和检索流程。SQLite 适合单机 CLI 和单元测试，但不能充分体现服务端常见的连接池、并发访问、事务边界、索引和数据库迁移能力。

个人项目需要在理解 Agent 原理的基础上，补充更接近实际后端项目的持久化实践。因此数据库升级是工程能力增强，不是 Agent Runtime 本身的创新点。

## 决策

使用 MySQL 8 作为默认运行时主存储：

- 会话、消息、工具调用日志、文档元数据和文档 Chunk 均存储在 MySQL。
- 使用 SQLAlchemy 2.x 作为数据库访问层，使用连接池管理连接。
- 使用 Alembic 管理表结构迁移。
- 使用 Docker Compose 提供本地 MySQL 8 环境。
- 中文词法检索使用 InnoDB `FULLTEXT` 的 ngram parser。
- Chroma 仅作为可选向量索引，MySQL 保存文档和 Chunk 的事实数据。
- SQLite 保留为测试适配器，不作为默认生产存储，也不作为简历主描述。

## 数据边界

```text
MySQL
├── sessions       会话
├── messages       对话消息
├── tool_logs      工具调用观察与结果
├── documents      文档元数据与 checksum
└── chunks         文档分块、页码和来源

Chroma（可选）
└── chunk_id -> embedding
```

MySQL 是文档和 Runtime 状态的唯一事实源。向量索引丢失时，可以根据 MySQL 中的 Chunk 重建，不能反过来只依赖 Chroma 保存业务数据。

## 实施要求

1. 定义 `SessionStore`、`ToolLogStore` 和 `KnowledgeStore` 等接口，Agent 主循环不得直接导入 MySQL 或 SQLite 驱动。
2. 所有写操作使用明确事务边界；消息和会话更新时间应保持一致。
3. 会话、消息、工具日志、文档和 Chunk 建立必要的外键与索引。
4. 文档使用稳定 `doc_id` 和 checksum，重复入库必须幂等，更新文档必须在事务内替换旧 Chunk。
5. 数据库连接、密码和 DSN 只能来自环境变量，不得提交到仓库或写入日志。
6. 集成测试启动独立 MySQL 实例，覆盖重启恢复、并发写入、事务回滚、重复入库和迁移升级。
7. 单元测试仍可使用 SQLite 适配器，但必须至少有一组 MySQL 集成测试证明 SQL 兼容性和真实索引行为。

## 选择 MySQL 而不是 PostgreSQL

- MySQL 8 与目标后端岗位常见技术栈一致，便于展示已有数据库基础向服务端实践迁移。
- 本项目需要的事务、外键、连接池和 ngram 全文检索，MySQL 8 均可支持。
- PostgreSQL + pgvector 也是合理方案，但会把项目重点进一步推向 PostgreSQL/向量数据库生态；当前优先选择 MySQL 以控制学习和实现范围。

## 代价与风险

- 本地运行从单文件数据库变为需要 Docker/MySQL 服务，环境准备更复杂。
- MySQL ngram 检索与 SQLite FTS5 的查询语法和排序行为不同，需要重新编写检索测试。
- SQLAlchemy 抽象会增加依赖，但能避免 Runtime 与具体数据库耦合。
- MySQL 与 Chroma 的一致性不是分布式事务；向量索引必须支持从 MySQL Chunk 重建。

## 验收标准

- 默认配置能够连接 MySQL 8 并完成迁移。
- Agent 重启后能够恢复会话和消息。
- 工具调用日志能够写入、查询，并在事务失败时回滚。
- 同一文档重复入库不会产生重复 Chunk，修改文档只更新受影响内容。
- MySQL ngram 检索和 Chroma 向量检索能够分别运行；向量依赖不可用时回退到 MySQL 检索。
- SQLite 适配器测试和 MySQL 集成测试均通过。
