# Build frontend in the first stage.
# 与 .nvmrc、package.json engines 和 GitHub Actions 保持一致。
FROM node:22.23.1-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Python runtime.
# Python 3.11：与 .github/workflows/docker.yml 的测试基线、uv.lock 解析目标一致。
FROM python:3.11-slim AS production

# Version and build time metadata injected via build args (e.g. CI / Docker build).
ARG APP_VERSION=dev
ARG GIT_SHA=unknown
ARG GIT_BRANCH=unknown
ARG BUILD_TIME=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  TZ=Asia/Shanghai \
  TG_SIGNER_DATA_DIR=/data \
  APP_VERSION=${APP_VERSION} \
  GIT_SHA=${GIT_SHA} \
  GIT_BRANCH=${GIT_BRANCH} \
  BUILD_TIME=${BUILD_TIME}

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential tzdata gosu && \
  rm -rf /var/lib/apt/lists/*

# 依赖单独成层：仅 pyproject.toml / uv.lock 变化才失效，
# 源码改动不会触发依赖重装。uv.lock 是依赖的唯一真相来源——
# 历史上此处曾手工罗列一套依赖覆盖 pip 解析结果，导致镜像里的
# fastapi 0.109.2 + httpx 0.28 组合把 starlette TestClient 打挂，
# 且镜像版本与 pyproject 声明静默分叉。
# 注意：pyotp 直接使用官方依赖（pip 安装），仓库不再提供根级 pyotp.py shim，勿在此 COPY。
COPY pyproject.toml README.md uv.lock /app/
COPY tg_signer/__init__.py /app/tg_signer/__init__.py

# tgcrypto 为 C 扩展，仅在 amd64 安装；arm64 走 kurigram 纯 Python 回退
# （ kurigram 启动时会打印 TgCrypto missing 提示，属预期行为）。
ARG TARGETPLATFORM
RUN pip install --no-cache-dir uv && \
  if [ "${TARGETPLATFORM:-}" = "linux/amd64" ] || [ "$(uname -m)" = "x86_64" ]; then \
    uv export --format requirements-txt --no-hashes --extra speedup --no-emit-project \
      -o /tmp/requirements.txt; \
  else \
    uv export --format requirements-txt --no-hashes --no-emit-project \
      -o /tmp/requirements.txt; \
  fi && \
  pip install --no-cache-dir -r /tmp/requirements.txt && \
  rm -f /tmp/requirements.txt

COPY backend /app/backend
COPY tg_signer /app/tg_signer
COPY plugins /app/plugins
COPY community_plugins /app/community_plugins

# 项目本体：依赖已由上面的锁装齐，--no-deps 避免二次解析破坏锁的确定性。
RUN pip install --no-cache-dir --no-deps .

# Frontend static files served from /web.
COPY --from=frontend-builder /frontend/dist /web

# Data dir + non-root user + entrypoint.
ARG APP_UID=10001
ARG APP_GID=10001
RUN mkdir -p /data && \
  groupadd -r -g ${APP_GID} app && \
  useradd -r -u ${APP_UID} -g app -d /app -s /usr/sbin/nologin app && \
  chown -R app:app /data

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080

# Healthcheck uses the PORT env var.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.getenv(\"PORT\", \"8080\")}/healthz').read()"

# Start with env-driven PORT (Zeabur sets this automatically).
ENTRYPOINT ["/entrypoint.sh"]
