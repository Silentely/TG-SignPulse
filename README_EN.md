<p align="center">
  <img src="docs/public/logo.svg" width="80" height="80" alt="TG-SignPulse Logo">
</p>

<h1 align="center">TG-SignPulse</h1>

<p align="center">
  <strong>Telegram Multi-Account Automation Panel</strong><br>
  Check-ins · Action Workflows · Keyword Monitoring · AI Verification
</p>

<p align="center">
  <a href="https://github.com/Silentely/TG-SignPulse/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-green" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.10--3.13-blue" alt="Python">
  <img src="https://img.shields.io/badge/node-22+-green" alt="Node.js">
  <a href="https://github.com/Silentely/TG-SignPulse/pkgs/container/tg-signpulse"><img src="https://img.shields.io/badge/ghcr.io-available-purple" alt="GHCR"></a>
  <a href="https://tg.cosr.eu.org/"><img src="https://img.shields.io/badge/docs-online-229ED9" alt="Docs"></a>
</p>

<p align="center">
  <a href="https://tg.cosr.eu.org/"><strong>Online Docs</strong></a>
  ·
  <a href="README.md">中文说明</a>
  ·
  <a href="https://tg.cosr.eu.org/guide/quick-start">Quick Start</a>
</p>

---

## Overview

TG-SignPulse is a Telegram automation panel. Manage multiple accounts, configure automated check-in tasks, and run them on fixed schedules or random time ranges — all from a web UI.

> 🤖 AI-powered: Integrated with OpenAI-compatible APIs for image recognition, math challenges, OCR, and more.

---

## Features

| Area | Capability |
|------|-----------|
| **Account Management** | Multi-account login (SMS/QR), proxy, status checks, re-login |
| **Task Workflows** | Fixed / random-range / listen-trigger execution modes |
| **Action Types** | Send text, click button, send dice, AI vision, AI calculate, keyword monitor |
| **Topic Support** | Send and filter by Telegram group Thread ID |
| **Keyword Monitoring** | Contains/exact/regex match → Telegram Bot, forward, Bark, custom URL, continue actions |
| **Notifications** | Task failure, invalid session, login, keyword match alerts |
| **Operations** | Docker deploy, persistent data, health checks, config import/export |

---

## Tech Stack

```
┌─────────────────────────────────────────────────────────┐
│  Frontend          Vue 3 + Vue Router + Pinia           │
│                    Tailwind CSS 4 + Lucide Icons         │
│                    Vite + PWA                            │
├─────────────────────────────────────────────────────────┤
│  Backend           FastAPI + Uvicorn                     │
│                    SQLAlchemy + SQLite (WAL)             │
│                    APScheduler (AsyncIO)                 │
│                    JWT + TOTP 2FA + bcrypt               │
├─────────────────────────────────────────────────────────┤
│  Telegram Engine   Pyrogram / Kurigram                   │
│                    Session File / String dual mode       │
├─────────────────────────────────────────────────────────┤
│  AI Integration    OpenAI SDK (compatible APIs)          │
│                    Vision / OCR / Math / Inference       │
├─────────────────────────────────────────────────────────┤
│  Infrastructure    Docker Multi-stage Build              │
│                    GitHub Actions CI/CD                   │
│                    GHCR Container Registry               │
└─────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Docker 24+ with Docker Compose
- At least one Telegram account

### One-command Deploy

```bash
docker run -d \
  --name tg-signpulse \
  --restart unless-stopped \
  -p 8080:8080 \
  -v $(pwd)/data:/data \
  -e TZ=Asia/Shanghai \
  -e APP_SECRET_KEY=$(openssl rand -base64 32) \
  -e ADMIN_PASSWORD=your_strong_password \
  ghcr.io/silentely/tg-signpulse:latest
```

### Docker Compose

```yaml
services:
  app:
    image: ghcr.io/silentely/tg-signpulse:latest
    container_name: tg-signpulse
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    environment:
      - TZ=Asia/Shanghai
      - APP_SECRET_KEY=your_secret_key
      - ADMIN_PASSWORD=your_strong_password
```

```bash
docker compose up -d
```

### Login

Open `http://YOUR_SERVER_IP:8080`

- Username: `admin`
- Password: your `ADMIN_PASSWORD` (or check `data/.admin_bootstrap_password` if not set)

---

## Project Structure

```text
TG-SignPulse/
├── backend/            # FastAPI backend
│   ├── api/            #   API routes
│   ├── core/           #   Config, auth, database
│   ├── models/         #   SQLAlchemy models
│   ├── services/       #   Business logic
│   ├── scheduler/      #   APScheduler
│   └── utils/          #   Utilities
├── tg_signer/          # Telegram automation engine
│   ├── core.py         #   Sign-in execution core
│   ├── config.py       #   Task config models (V1→V2→V3)
│   └── ai_tools.py     #   AI tool integration
├── frontend/           # Vue 3 frontend
├── docker/             # Docker entrypoint
├── docs/               # Project documentation
├── Dockerfile          # Multi-stage build
├── docker-compose.yml  # Compose orchestration
└── pyproject.toml      # Python project config
```

---

## Documentation

Full docs: **[https://tg.cosr.eu.org](https://tg.cosr.eu.org/)**

| Page | Description |
|------|-------------|
| [Quick Start](https://tg.cosr.eu.org/guide/quick-start) | Deploy and create your first task |
| [Docker](https://tg.cosr.eu.org/deploy/docker) | Images, Compose, upgrades |
| [Configuration](https://tg.cosr.eu.org/reference/configuration) | Env vars and data directory |
| [Ops](https://tg.cosr.eu.org/reference/ops) | Health checks, backup, go-live |
| [FAQ](https://tg.cosr.eu.org/faq) | Troubleshooting |

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_SECRET_KEY` | JWT secret (required in production) | Auto-generated |
| `ADMIN_PASSWORD` | Initial admin password | Random |
| `APP_DATA_DIR` | Data directory | `/data` |
| `APP_DATABASE_URL` | Optional; empty = SQLite, or Postgres URL | empty |
| `TZ` | Timezone | `Asia/Shanghai` |
| `TG_SESSION_MODE` | Session mode `file`/`string` | `file` |
| `TG_GLOBAL_CONCURRENCY` | Global concurrency limit | `1` |
| `TG_PROXY` | Global Telegram proxy | None |

See [Configuration Reference](https://tg.cosr.eu.org/reference/configuration) for the full list.

---

## Local Development

```bash
# Backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn backend.main:app --reload --port 8080

# Frontend
cd frontend
npm ci
npm run dev
```

- Python 3.10–3.13 (3.12 recommended)
- Node.js 22.12.0+
- Python 3.14+ is not recommended (Telegram runtime deps not yet compatible)

---

## Health Checks

```bash
curl http://127.0.0.1:8080/healthz   # Quick health check
curl http://127.0.0.1:8080/readyz    # Readiness check
```

---
## Acknowledgements

Based on [tg-signer](https://github.com/amchii/tg-signer) by [amchii](https://github.com/amchii), heavily refactored and extended.

---

## License

[BSD-3-Clause](LICENSE)
