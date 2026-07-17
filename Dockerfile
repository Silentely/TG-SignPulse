FROM node:22-slim AS frontend-builder

WORKDIR /frontend

# Copy dependency manifests first for better layer caching.
COPY frontend/package*.json ./
RUN npm install --prefer-offline

COPY frontend/ ./
# Skip vue-tsc type check (already done in CI), only run vite build
RUN npx vite build


FROM python:3.12-slim AS app

ARG GIT_SHA=dev
ARG GIT_BRANCH=dev
# 空表示使用包内 __version__；CI 构建会注入真实版本
ARG APP_VERSION=
ARG BUILD_TIME=
ENV PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PIP_DISABLE_PIP_VERSION_CHECK=1 \
  PIP_NO_CACHE_DIR=1 \
  PORT=8080 \
  TZ=Asia/Shanghai \
  GIT_SHA=${GIT_SHA} \
  GIT_BRANCH=${GIT_BRANCH} \
  APP_VERSION=${APP_VERSION} \
  BUILD_TIME=${BUILD_TIME}

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential tzdata gosu && \
  rm -rf /var/lib/apt/lists/*

# Install all Python dependencies in a single layer for faster builds.
COPY pyproject.toml pyotp.py README.md /app/
COPY tg_signer/__init__.py /app/tg_signer/__init__.py
COPY backend /app/backend
COPY tg_signer /app/tg_signer

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
