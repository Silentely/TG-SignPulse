# Build frontend in the first stage.
# 与 .nvmrc、package.json engines 和 GitHub Actions 保持一致。
FROM node:22.23.1-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Python runtime.
# Python 3.11 for Telethon + dependencies.
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

# Install all Python dependencies in a single layer for faster builds.
# 注意：pyotp 直接使用官方依赖（pip 安装），仓库不再提供根级 pyotp.py shim，勿在此 COPY。
COPY pyproject.toml README.md /app/
COPY tg_signer/__init__.py /app/tg_signer/__init__.py
COPY backend /app/backend
COPY tg_signer /app/tg_signer
COPY plugins /app/plugins

ARG TARGETPLATFORM
RUN pip install --no-cache-dir . \
  "pydantic<2" \
  "fastapi==0.109.2" \
  "bcrypt==4.0.1" \
  uvicorn[standard] \
  sqlalchemy \
  "passlib[bcrypt]==1.7.4" \
  pyotp \
  qrcode[pil] \
  apscheduler \
  python-multipart \
  && if [ "${TARGETPLATFORM:-}" = "linux/amd64" ] || [ "$(uname -m)" = "x86_64" ]; then \
    pip install --no-cache-dir tgcrypto; \
  fi

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
