# TG-SignPulse

[中文说明](README.md)

TG-SignPulse is a Telegram automation panel. It helps you manage multiple accounts, run auto check-in tasks, and monitor execution logs from a web UI.

> AI-powered: AI actions (vision/math) are integrated and can be used directly in task workflows.

## What Is This Project For?

- Manage multiple Telegram accounts in one place
- Automate check-ins, message sending, and button clicking
- Use AI actions for image recognition and math challenges
- View execution flow logs and recent bot replies
- Run check-ins inside specific Telegram group topics
- Use clipboard bulk task import/export, global proxy fallback, failure notifications, and keyword monitoring
- Run reliably on a VPS for long-term automation

## Key Features

- Multi-account management
- Action sequences: `Send Text`, `Click Text Button`, `Send Dice`, `AI Vision`, `AI Calculate`, `Keyword Monitor`
- Topic check-ins for specific Thread/Topic IDs in Telegram forum groups
- Task migration via clipboard export/import with duplicate skipping
- Telegram Bot failure notifications, keyword-match notifications, and dashboard invalid-session hints when all tasks under an account fail
- Visual logs with per-run flow details and latest bot replies
- Stability improvements for timeout/429 scenarios and long-running memory behavior
- Docker-first deployment (easy to start and migrate)

## Beginner Deployment (3 Steps)

1. Install Docker
2. Run the container command below
3. Open `http://YOUR_SERVER_IP:8080` in a browser and log in

Default credentials:
- Username: `admin`
- Password: `admin123`

### One-command Deploy

```bash
docker run -d \
  --name tg-signpulse \
  --restart unless-stopped \
  -p 8080:8080 \
  -v $(pwd)/data:/data \
  -e TZ=Asia/Shanghai \
  -e APP_SECRET_KEY=your_secret_key \
  ghcr.io/akasls/tg-signpulse:latest
```

If you use a reverse proxy, bind locally only:

```bash
-p 127.0.0.1:8080:8080
```

### Docker Compose (Optional)

```yaml
services:
  app:
    image: ghcr.io/akasls/tg-signpulse:latest
    container_name: tg-signpulse
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    environment:
      - TZ=Asia/Shanghai
      - APP_SECRET_KEY=your_secret_key
```

## Data Directory & Permissions

- Default data directory: `/data`
- If `/data` is not writable, app falls back to `/tmp/tg-signpulse` (non-persistent)
- New images can auto-adapt runtime UID/GID to `/data` owner in most VPS setups (usually no need for `chmod 777`)

Container checks:

```bash
id
ls -ld /data
touch /data/.probe && rm /data/.probe
```

## Common Environment Variables

- `APP_SECRET_KEY`: panel secret key (strongly recommended)
- `ADMIN_PASSWORD`: initial default password for the admin user (strongly recommended, otherwise defaults to insecure 'admin123')
- `APP_HOST`: API listening interface (defaults to `127.0.0.1` for security; use `0.0.0.0` if exposing container globally)
- `APP_DATA_DIR`: custom data directory (higher priority than panel setting)
- `TG_PROXY`: Telegram connection proxy; you can also configure a global proxy in the panel
- `TG_SESSION_MODE`: `file` (default) or `string` (recommended on arm64)
- `TG_SESSION_NO_UPDATES`: set `1` to enable `no_updates` (`string` mode only)
- `TG_GLOBAL_CONCURRENCY`: global concurrency limit (default `1`)
- `APP_TOTP_VALID_WINDOW`: panel 2FA tolerance window

## Custom Data Directory

You can set the data directory in two ways:

1. Panel: `System Settings -> Global Sign-in Settings -> Data Directory`
2. Env var: `APP_DATA_DIR=/your/path`

Notes:
- Restart backend service after changing it
- The path must be writable and mounted as persistent volume

## Common Panel Settings

In `System Settings -> Global Sign-in Settings`, you can configure:

- Global Proxy: used by login, chat refresh, and task execution when an account has no dedicated proxy
- Telegram Bot Failure Notifications: set Bot Token and target Chat ID to receive failed-task alerts
- Data Directory: stores sessions, logs, database, and task files

On the account task page, you can:

- Fill in `Topic / Thread ID` so a task only runs inside a specific Telegram group topic
- Add `Keyword Monitor` to an ordered action sequence to push matched messages to Telegram Bot, Bark, a custom URL, or forward them to a target Chat ID/topic ID
- Click the top-right export icon to copy all tasks of the current account to the clipboard
- Click the top-right paste/import action to bulk-import tasks from the clipboard while skipping duplicates

## Health Checks

- `GET /healthz`: quick health endpoint
- `GET /readyz`: readiness endpoint

## Project Structure

```text
backend/      FastAPI backend and scheduler
tg_signer/    Telegram automation core
frontend/     Next.js management panel
```

## Changelog

### 2026-04-27

- **Keyword Monitor Action**: Keyword monitoring now lives in the account task ordered action sequence, so it can be configured per task, account, chat, and topic.
- **Matched Message Forwarding**: Matched messages can be forwarded to a target Chat ID, with optional topic/thread ID support.
- **Custom Push Channels**: Keyword matches can still notify via Telegram Bot, Bark, or a custom push URL; forwarding failures no longer block the later push notification.
- **Keyword Monitor Layout**: Keywords, match mode, ignore-case, forward Chat ID, topic ID, push channel, and push URL are now shown as one parameter per row to avoid cramped controls.

### 2026-04-26

- **Telegram Topic (Thread) Support**: Tasks can now run inside a specific topic of a specific group. Sent messages include `message_thread_id`, and incoming replies from other topics are ignored.
- **Global Proxy Fallback**: Added a Global Proxy setting. Login, chat refresh, scheduled/manual task execution, and legacy CLI execution use it whenever an account does not have its own proxy.
- **Clipboard Bulk Import/Export**: The account task page now has top-right actions to export all tasks to the clipboard and paste-import tasks. Imports skip duplicates and attach imported tasks to the current account.
- **Convenient Re-login Experience**: The account edit modal now includes a Re-login action with complete Chinese/English labels, allowing users to refresh an existing account session directly.
- **Telegram Bot Failure Notifications**: System Settings now include notification enablement, Bot Token, and notification Chat ID. Failed tasks send account, task, error, and recent log context.
- **Dashboard Invalid-Session Hint**: If every task under an account failed in its latest run, the dashboard marks the account as session invalid and guides users to re-login.
- **Frontend Task Log Improvements**: Per-run task flow logs retain more lines and are shown directly in the frontend task history.
- **Project Health Cleanup**: Fixed simple Ruff findings and made root debug scripts safe for pytest collection.

### 2026-03-20
- **SQLite Database Deadlock Fixed**: Hardened the Pyrogram client lifecycle cache, completely eliminating the overlapping `database is locked` errors previously caused by concurrent UI polling overlapping with worker queues. Background executions now smoothly multiplex SQLite connections, resulting in significantly lower I/O and zero queuing deadlocks.
- **Task Prevention UI**: Improved the frontend with protection logic against double-calling tasks. If the user accidentally clicks 'Run' on an actively executing task, the app will gracefully block the action, display a warning that the task is currently in progress, and immediately pivot to streaming its live logs instead.

### 2026-03-19

- **Account Status Display Fix**: Fixed a frontend string-matching bug where completely normal accounts were erroneously displayed as "Account Invalid".
- **Old Account Execution Fix**: Resolved critical `PeerIdInvalid` execution crashes for older local `.session` file-based accounts. The task engine was mistakenly defaulting them into an in-memory session mode overriding their reliable local SQLite database, resulting in a loss of tracked peers. Now, caching and cross-account task copying are highly stable.
- **Bot Final Reply Extraction**: Enhanced log parsing engine. During successful message exchanges, the engine automatically extracts the final reply text from the target signed-bot and presents it beautifully in both the frontend run logs and execution table, keeping the UI intact. 
- **Code Linter**: Ran full project health & Ruff linter checks, safely pruning dead code.

### 2026-03-12
- Core stability fix: Fixed a severe memory leak and high network I/O issue caused by Pyrogram timeout & `FloodWait` infinite retry loops leading to async lock starvation and unretrieved task exceptions.

### 2026-03-06

- Action sequence order optimized: `Send Text -> Click Text Button -> Send Dice -> AI Vision -> AI Calculate`.
- AI actions refined: `AI Vision` and `AI Calculate` now support inline sub-modes (send text / click button).
- Task copy/paste UX improved:
  - Copy now opens a config dialog with one-click copy.
  - Top-right paste import tries clipboard first; falls back to manual paste dialog when unavailable.
- Task log dialog improved: now shows `Task: XXX succeeded/failed` and the latest bot reply.
- Dashboard status checks improved on page open/refresh to reduce false "Check Failed".
- Mobile/layout polish: task card action area is more compact, action-row control heights are unified.
- UTF-8 export fix: resolved task copy/export errors with emoji content.
- Container permission compatibility improved with `/data` owner UID/GID adaptation.

### 2026-03-01

- AI action upgrade, AI config save fix, and phone code login changed to manual confirmation.
- Reduced frequent `TimeoutError` and `429 transport flood` logs.
- Long-running stability and memory optimizations.
- Added custom data directory support.

## Acknowledgements

This project is heavily refactored and extended based on the original project:

- Original project: [tg-signer](https://github.com/amchii/tg-signer) by [amchii](https://github.com/amchii)

Tech stack: FastAPI, Uvicorn, APScheduler, Pyrogram/Kurigram, Next.js, Tailwind CSS, OpenAI SDK.
