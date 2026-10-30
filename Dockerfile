# AgentKernel CLI 镜像（P0-3）
# - 多阶段构建；运行阶段非 root（uid/gid 10001）
# - 基础镜像固定到精确 patch tag；digest 待补（G-46：本机无法访问 registry-1.docker.io）
#   HEALTHCHECK 只证明进程能起来（--help），不代表运行态健康；运行态由 smoke 与 CI 测试覆盖
# - 只装 core + mysql extras；rag（chromadb/sentence-transformers/torch）不进默认镜像，
#   需要时本地 `uv sync --extra rag`（见 docs/production-standard.md §4.1）
# - smoke 只证明「能启动 + /quit」；MySQL 行为由 CI 的 MySQL service 测试覆盖，本镜像不宣称已验证 MySQL
#
# 本地若 docker.io 不可达，可用国内镜像覆盖基础镜像：
#   docker build --build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.11-slim -t agentkernel:local .
ARG PYTHON_IMAGE=python:3.11.15-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff

FROM ${PYTHON_IMAGE} AS builder
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
# uv 版本与本地/CI 一致，避免 lock 解析行为差异
RUN pip install --no-cache-dir uv==0.11.29
WORKDIR /app
# 先装依赖层，源码变动时可复用缓存
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --extra mysql
# 再装项目本身（--no-editable：把包装进 venv，运行阶段不需要源码树）
COPY src ./src
RUN uv sync --frozen --no-editable --extra mysql

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
# 迁移入口需要 alembic.ini + migrations（--migrate）
COPY alembic.ini ./
COPY migrations ./migrations
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -m agentkernel --help > /dev/null || exit 1
# 不设 ENTRYPOINT：保持 `docker run <image> python -m agentkernel ...` 这种显式调用（与 README/CI 一致）
CMD ["python", "-m", "agentkernel", "--help"]
