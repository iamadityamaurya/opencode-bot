# OpenCode Telegram Remote Controller — Implementation Walkthrough

This document provides a comprehensive, step-by-step implementation guide for building a secure, local-first Telegram bot that remotely controls an OpenCode server instance on a Linux host.

---

## 1. System Overview & Architecture

The OpenCode Telegram Remote Controller acts as a bridge between your mobile/desktop Telegram client and a local OpenCode server running in headless mode (`opencode serve`).

### Architecture Diagram

```mermaid
flowchart TD
    subgraph Client["Telegram Client"]
        TGUser["User (Phone / Desktop)"]
    end

    subgraph BotService["Telegram Bot Process (Python)"]
        TGHandler["Telegram Handlers & UI"]
        AuthLayer["Authorization & Allowlist Check"]
        TaskOrch["Task Orchestration & Concurrency"]
        DB[(SQLite Persistence)]
        HTTPClient["Async OpenCode HTTP Client"]
        SSEListener["SSE Event Stream Listener"]
    end

    subgraph Host["Linux Local Host (Loopback Only)"]
        OpenCodeServer["OpenCode Server (127.0.0.1:4096)"]
        ProjectDir["Allowed Project Directory"]
    end

    TGUser <-->|Telegram Bot API / Polling| TGHandler
    TGHandler --> AuthLayer
    AuthLayer --> TaskOrch
    TaskOrch <--> DB
    TaskOrch --> HTTPClient
    HTTPClient <-->|HTTP / REST API| OpenCodeServer
    SSEListener <-->|Server-Sent Events| OpenCodeServer
    OpenCodeServer <-->|File operations & Tools| ProjectDir
```

### Core Design Principles
1. **API-First (Headless Server)**: Interacts strictly with OpenCode's documented HTTP/SSE endpoints. Avoids brittle screen scraping or terminal parsing.
2. **Defense-In-Depth Security**: Bound strictly to `127.0.0.1`. Strict Telegram user ID allowlist and path traversal protection for project directories.
3. **Non-Blocking & Asynchronous**: Built with Python `asyncio`, keeping Telegram update polling responsive while background AI tasks execute.
4. **Durable State Management**: Persistent SQLite storage ensures active project choices, session contexts, and running tasks survive bot restarts.

---

## 2. Prerequisites & Setup

### Requirements
- Linux OS (with `systemd --user` support)
- Python 3.10+
- Installed `opencode` CLI tool
- A Telegram account and Bot Token from [@BotFather](https://t.me/BotFather)

### Environment Configuration

Create a `.env` file in the project directory:

```env
TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
TELEGRAM_ALLOWED_USER_IDS="123456789,987654321"
OPENCODE_BASE_URL="http://127.0.0.1:4096"
DATABASE_PATH="./data/bot.sqlite3"
LOG_LEVEL="INFO"
```

Create a `config.toml` file for project allowlisting:

```toml
[server]
base_url = "http://127.0.0.1:4096"
connect_timeout_seconds = 5
request_timeout_seconds = 600

[projects]
default = "opencode-bot"

[projects.opencode-bot]
path = "/home/aditys/code/opencode_extension/opencode-bot"

[bot]
max_active_tasks_per_session = 1
progress_update_interval_seconds = 10
max_telegram_message_length = 4000
```

---

## 3. Detailed Implementation Roadmap

### Phase 1: OpenCode API Integration Layer (`opencode/client.py`)

Build an asynchronous HTTP client wrapper using `httpx` to interface with `http://127.0.0.1:4096`.

Key Endpoints to Wrap:
- `GET /global/health`: Server health check.
- `POST /session`: Create new OpenCode session.
- `GET /session`: List active sessions.
- `POST /session/{id}/prompt_async`: Submit non-blocking prompt.
- `POST /session/{id}/abort`: Abort running task.
- `GET /session/{id}/diff`: Inspect file modifications.
- `GET /event`: Open SSE stream for real-time progress updates.

```python
# Example Client Structure snippet
import httpx

class OpenCodeClient:
    def __init__(self, base_url: str):
        self.client = httpx.AsyncClient(base_url=base_url, timeout=30.0)

    async def check_health(self) -> bool:
        resp = await self.client.get("/global/health")
        return resp.status_code == 200

    async def create_session(self, title: str | None = None) -> dict:
        resp = await self.client.post("/session", json={"title": title})
        resp.raise_for_status()
        return resp.json()

    async def send_prompt_async(self, session_id: str, prompt: str) -> dict:
        resp = await self.client.post(f"/session/{session_id}/prompt_async", json={"prompt": prompt})
        resp.raise_for_status()
        return resp.json()
```

---

### Phase 2: Security & Authorization Engine (`bot/authorization.py`)

Every incoming update (commands, text messages, inline button callbacks) must pass authorization checks.

1. **User Allowlist Verification**: Reject updates where `user.id` is not in `TELEGRAM_ALLOWED_USER_IDS`.
2. **Project Path Validation**: Validate configured project paths using `pathlib.Path.resolve()` to prevent directory traversal attacks or symlink escapes.

```python
from pathlib import Path

def is_user_authorized(user_id: int, allowed_ids: set[int]) -> bool:
    return user_id in allowed_ids

def validate_project_path(requested_path: str, allowed_roots: list[Path]) -> Path:
    resolved = Path(requested_path).resolve()
    for root in allowed_roots:
        if root.resolve() in resolved.parents or resolved == root.resolve():
            return resolved
    raise ValueError("Access to path outside allowed directory is denied.")
```

---

### Phase 3: Persistence & Database Schema (`storage/database.py`)

Use SQLite to store user state, active project selections, active session mapping, and task states across bot restarts.

```sql
-- Schema Overview
CREATE TABLE IF NOT EXISTS user_states (
    telegram_user_id INTEGER PRIMARY KEY,
    selected_project TEXT,
    selected_session_id TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    project_name TEXT NOT MAIN,
    telegram_user_id INTEGER,
    title TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    telegram_user_id INTEGER NOT NULL,
    state TEXT CHECK(state IN ('queued', 'running', 'awaiting_permission', 'completed', 'failed', 'cancelled')),
    prompt TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

### Phase 4: Telegram Interface & Command Handlers (`bot/handlers.py`)

Implement commands using `python-telegram-bot`:

| Command | Action |
|---|---|
| `/start` | Display welcome, authorization status, and quick command guide |
| `/projects` | List available allowlisted projects |
| `/project <name>` | Select active working project |
| `/new` | Spawn a new OpenCode session in active project |
| `/sessions` | List sessions in current project |
| `/session <id>` | Select active session |
| `/ask <prompt>` | Submit coding task to active session |
| `/status` | View running task state, session status, and server health |
| `/stop` | Abort active task in current session |
| `/diff` | Show file modification summary |

---

### Phase 5: Task Orchestration & Concurrency Control (`services/tasks.py`)

To prevent overlapping edits or race conditions:
1. Enforce a **single active prompt per session** using in-process `asyncio.Lock` paired with SQLite state locks.
2. Mark tasks `queued` -> `running` -> `completed` / `failed` / `cancelled`.
3. Support non-blocking operation: `/ask` returns immediately with a Task ID acknowledgement while the task executes asynchronously.

---

### Phase 6: Event Listener & Permission Workflow (`opencode/events.py`)

Connect to `GET /event` via HTTP SSE streaming to receive live updates.

1. **Progress Throttling**: Batch token/tool updates and send progress reports at configurable intervals (e.g., every 10s) to respect Telegram rate limits.
2. **Interactive Permissions**: When an event indicates OpenCode requires user approval for a tool/file operation:
   - Send an inline message with **Approve** and **Deny** buttons.
   - Upon button click, validate user identity and post the resolution back to OpenCode's permission response endpoint.

---

### Phase 7: Linux `systemd` User Service Setup (`systemd/`)

Manage both OpenCode server and the Telegram bot as user services on Linux.

`~/.config/systemd/user/opencode-server.service`:
```ini
[Unit]
Description=OpenCode Headless Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/aditys/code/opencode_extension/opencode-bot
ExecStart=/usr/local/bin/opencode serve --hostname 127.0.0.1 --port 4096
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

`~/.config/systemd/user/opencode-telegram.service`:
```ini
[Unit]
Description=OpenCode Telegram Remote Control Bot
After=opencode-server.service

[Service]
Type=simple
WorkingDirectory=/home/aditys/code/opencode_extension/opencode-bot
ExecStart=/usr/bin/python3 -m opencode_telegram.main
Restart=always
RestartSec=5
EnvironmentFile=/home/aditys/code/opencode_extension/opencode-bot/.env

[Install]
WantedBy=default.target
```

Enable user lingering so services run without an active SSH session:
```bash
loginctl enable-linger aditys
systemctl --user daemon-reload
systemctl --user enable --now opencode-server.service
systemctl --user enable --now opencode-telegram.service
```

---

## 4. Testing & Verification Checklist

### Unit & Integration Testing
- [ ] Test authorization rejection for unauthorized Telegram user IDs.
- [ ] Test path validation against symlink escapes.
- [ ] Verify HTTP client error handling when OpenCode server is unreachable.
- [ ] Verify message length chunking logic for large outputs (>4000 characters).

### Manual Acceptance Flow
1. **Startup Check**: Run `curl http://127.0.0.1:4096/global/health`.
2. **Bot Initialization**: Send `/start` from Telegram. Ensure only allowed user ID gets access.
3. **Project & Session Setup**: Select project using `/project opencode-bot`, then create session using `/new`.
4. **Execute Coding Task**: Send `/ask Create a hello_world.py file with a main function`.
5. **Inspect Progress & Status**: Check `/status` while running, then review `/diff` when finished.
6. **Task Cancellation**: Trigger a long-running prompt and send `/stop` to verify graceful cancellation.
7. **Bot Recovery**: Restart bot process (`systemctl --user restart opencode-telegram`) and verify `/status` remembers active session.

---

## 5. Summary & Next Steps

1. Create Python package structure in `src/opencode_telegram/`.
2. Implement core modules sequentially according to Phase 1 through Phase 7.
3. Verify local OpenCode endpoints against `/doc`.
4. Deploy under systemd user services.
