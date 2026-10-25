<p align="center">
  <img src="docs/public/logo.svg" width="80" height="80" alt="TG-SignPulse Logo">
</p>

<h1 align="center">TG-SignPulse</h1>

<p align="center">
  <strong>Telegram Multi-Account Automation Management Panel</strong><br>
  Check-in · Task Workflows · Keyword Monitor · AI Verification · JEV Semantic Engine
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

> 🤖 **AI & Semantic Engine**: Integrated with OpenAI-compatible APIs (vision / math / OCR) and native **JEV Semantic Decision Engine** (SystemOne protocol for robust inline button deduction, tri-state circuit breaking, and rule self-healing suggestions).

---

## Visual Preview

<p align="center">
  <img src="docs/public/screenshots/dashboard.png" alt="TG-SignPulse Dashboard Overview" width="100%">
</p>

<details open>
<summary><strong>📸 Click to expand/collapse feature screenshots</strong></summary>
<br>

| Module | Features & Visual Preview |
| :--- | :--- |
| **Task Orchestration**<br>· Scheduled, random time window, and real-time listening modes<br>· Smart jitter peak-shaving & adaptive cooldown timers<br>· Multi-account task sharing and tagging | <a href="docs/public/screenshots/tasks.png"><img src="docs/public/screenshots/tasks.png" width="560" alt="Task Orchestration"></a> |
| **Action Flow & AI Verification**<br>· Drag-and-drop step workflow: text command, inline button click<br>· OpenAI-compatible AI vision: OCR, math question inference & button tapping<br>· Step error tolerance, skip conditions, and retry policy | <a href="docs/public/screenshots/task-editor.png"><img src="docs/public/screenshots/task-editor.png" width="560" alt="Action Flow & AI Verification"></a> |
| **Account Management**<br>· Multi-account session status monitoring & latency checks<br>· Independent proxy bindings & egress IP verification<br>· Device fingerprint profiles (macOS / Android / Windows) | <a href="docs/public/screenshots/accounts.png"><img src="docs/public/screenshots/accounts.png" width="560" alt="Account Management"></a> |
| **QR Login & Session Import**<br>· Official QR code login without typing phone numbers<br>· Seamless Telethon / Pyrogram `.session` and StringSession import<br>· Two-Factor Authentication (2FA) verification | <a href="docs/public/screenshots/account-modal.png"><img src="docs/public/screenshots/account-modal.png" width="560" alt="QR Login & Session Import"></a> |
| **Real-time Observability & Logs**<br>· Real-time SSE log streaming with millisecond sync<br>· 11 fine-grained failure categories with actionable hints<br>· Fast filtering by account, task, time, and one-click log export | <a href="docs/public/screenshots/logs.png"><img src="docs/public/screenshots/logs.png" width="560" alt="Real-time Observability & Logs"></a> |
| **System Settings & WebDAV Cloud Backup**<br>· Multi-channel alert matrix (Telegram Bot, Feishu, DingTalk, Discord)<br>· Encrypted WebDAV disaster recovery (`.spbak` format)<br>· Global concurrency, quiet hours, and scheduler hot reload | <a href="docs/public/screenshots/settings.png"><img src="docs/public/screenshots/settings.png" width="560" alt="System Settings & WebDAV Cloud Backup"></a> |
| **PWA Mobile Adaptation**<br>· Responsive mobile layout tailored for handheld touch screens<br>· Progressive Web App (PWA) support: install directly to phone home screen | <p align="center"><a href="docs/public/screenshots/mobile.png"><img src="docs/public/screenshots/mobile.png" width="280" alt="PWA Mobile Adaptation"></a></p> |

</details>

---

## Features

| Area | Capability |
|------|-----------|
| **Account Management** | Multi-account login, tagging, Telegram FloodWait backoff protection |
| **Task Workflows** | Fixed / random / listen modes, drag-and-drop actions, step error-tolerance & skip, safe AST macro engine |
| **Action Types** | Send text, click button, send dice, AI vision/calculate, keyword monitor, custom plugins |
| **JEV Semantic Engine** | Native SystemOne protocol, robust button deduction, tri-state circuit breaker (`closed`/`half_open`/`open`) fallback & intelligent rule suggestions |
| **Topic Support** | Send and filter by Telegram group Thread ID |
| **Keyword Monitoring** | Contains/exact/regex match → Telegram Bot, forward, Bark, custom URL, continue actions |
| **Notifications** | Alerts via TG Bot, WeCom, Feishu, DingTalk, Discord multi-channel matrix |
| **ChatOps & Ops** | TG Bot control (/status, /run, etc.), dashboard trend charts, WebDAV remote backup & archive export |

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
│  AI & Semantic     OpenAI SDK (Vision / OCR / Math)      │
│                    JEV Engine (SystemOne / Breaker)      │
├─────────────────────────────────────────────────────────┤
│  Infrastructure    Docker Multi-stage Build              │
│                    GitHub Actions CI/CD                  │
│                    GHCR Container Registry               │
└─────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Docker 24+ and Docker Compose
- At least one Telegram account

### One-Command Start

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

### Access Dashboard

Open `http://YOUR_SERVER_IP:8080` in browser.

- Username: `admin`
- Password: The `ADMIN_PASSWORD` you configured (or check `data/.admin_bootstrap_password` if unset)

---

## Project Structure

```text
TG-SignPulse/
├── backend/            # FastAPI backend
│   ├── api/            #   API routing (including semantic.py)
│   ├── core/           #   Config, auth, database
│   ├── models/         #   SQLAlchemy models
│   ├── services/       #   Business logic (including semantic/)
│   ├── scheduler/      #   APScheduler
│   └── utils/          #   Helper functions
├── tg_signer/          # Telegram automation engine
│   ├── core/           #   Signer core (client lifecycle / runtime)
│   ├── semantic/       #   JEV semantic client & SystemOne protocol
│   ├── config.py       #   Task config models (V1→V2→V3)
│   └── ai_tools.py     #   AI tools integration
├── frontend/           # Vue 3 frontend
│   ├── src/
│   └── vite.config.ts
├── docker/             # Docker entry scripts
├── docs/               # Documentation
├── Dockerfile          # Multi-stage build
├── docker-compose.yml  # Compose file
└── pyproject.toml      # Python project configuration
```

---

## Documentation

Full documentation is available at **[https://tg.cosr.eu.org](https://tg.cosr.eu.org/)**.

| Section | Description |
|---|---|
| [Quick Start](https://tg.cosr.eu.org/guide/quick-start) | Deploy and create your first task |
| [Docker Deployment](https://tg.cosr.eu.org/deploy/docker) | Container images, compose, upgrade |
| [JEV Semantic Engine](https://tg.cosr.eu.org/guide/jev) | SystemOne semantic decisions, circuit breaker & rule suggestions |
| [Configuration](https://tg.cosr.eu.org/reference/configuration) | Environment variables, data directories |
| [Ops Guide](https://tg.cosr.eu.org/reference/ops) | Health checks, backups, checklists |
| [Task Orchestration](https://tg.cosr.eu.org/guide/tasks) | sign-tasks, action types |
| [FAQ](https://tg.cosr.eu.org/faq) | Troubleshooting and Q&A |

---

## Key Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_SECRET_KEY` | JWT secret (required in prod) | auto-generated |
| `ADMIN_PASSWORD` | Initial admin password | randomly generated |
| `APP_DATA_DIR` | Data directory | `/data` |
| `APP_DATABASE_URL` | Optional DB URL; empty=SQLite | empty |
| `TZ` | Timezone | container `Asia/Shanghai` |
| `TG_SESSION_MODE` | Session mode `file`/`string` | `file` |
| `TG_GLOBAL_CONCURRENCY` | Global concurrency | auto (CPU cores, cap 5) |
| `TG_PROXY` | Global Telegram proxy | none |
| `ENABLE_API_DOCS` | Enable Swagger UI & OpenAPI docs | `false` |

---

## Local Development

```bash
# Backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn backend.main:app --reload --port 8080

# Frontend
nvm use
cd frontend
npm ci
npm run dev
```

- Python 3.10–3.13 (3.12 recommended)
- Node.js 22.23.1 (must match `.nvmrc`)
- Python 3.14+ is not recommended (Telegram runtime libraries not yet compatible)

---

## Health Checks

```bash
curl http://127.0.0.1:8080/healthz   # Quick liveness check
curl http://127.0.0.1:8080/readyz    # Service readiness check
```

---

## Acknowledgements

Based on and expanded from [tg-signer](https://github.com/amchii/tg-signer) by [amchii](https://github.com/amchii).

---

## License

[BSD-3-Clause](LICENSE)
