# OpenCode Telegram Remote Controller

A secure, local-first Telegram bot that allows developers to remotely control an OpenCode server running on a Linux machine via Telegram.

> **OpenCode V2.** This bot talks to the OpenCode **V2 HTTP API** (`/api/*`), which requires authentication. Set `OPENCODE_SERVER_PASSWORD` (HTTP basic auth; username `opencode` via `OPENCODE_SERVER_USERNAME`) and start the server with the same variable. See <https://opencode.ai/v2/docs/api/>.

## Features

- 🔒 **Defense-in-depth Security**: Loopback binding (`127.0.0.1`), Telegram user allowlist, and a strict project allowlist.
- ⚡ **Asynchronous & Non-Blocking**: Built with `asyncio`, keeping Telegram updates responsive during long AI tasks.
- 🛡️ **Interactive Security Approvals**: Respond to tool execution / file modification permission requests directly with Telegram inline buttons (`Approve` / `Deny`).
- 🤖 **Dynamic LLM Model Switcher**: Seamlessly switch models (e.g. Claude 3.5 Sonnet, GPT-4o, Gemini 2.0 Flash, DeepSeek R1) per session.
- 🎙️ **Voice & Attachment Support**: Send voice notes or code files/documents directly to Telegram for automated prompt execution.
- 💾 **Durable State**: SQLite persistence retains active project choices, session mappings, and task state across restarts.
- 📊 **Real-time Monitoring & Control**: Check task status, view git diff summaries, and interrupt tasks remotely.
- 📡 **Event-Driven Live Activity**: Subscribes to the OpenCode SSE stream (`/api/event`). Tasks complete the instant a turn ends (no polling lag), the acknowledgement message updates with the running tool/step, and task messages get 👀 / ✅ / ❌ / 🛑 reactions.
- 📌 **Heartbeat Status**: Optionally pins a self-updating status message per chat (active sessions, pending approvals, session cost).
- ⚙️ **Linux Service Ready**: Configured for `systemd --user` background execution.

## Live Activity Tuning

The `[bot]` section of `config.toml` controls the event-driven features:

```toml
[bot]
progress_edit_interval_seconds = 3   # min seconds between live progress edits
heartbeat_interval_seconds = 60      # 0 disables the pinned status heartbeat
enable_reactions = true              # 👀 / ✅ / ❌ / 🛑 on task messages
```

Completion is detected from the event stream and falls back to polling
(`progress_update_interval_seconds`) if the stream is quiet; final state is
always re-read from the messages API, so events only act as a fast trigger.

## Installation & Setup

1. **Install Dependencies** (from the project root):
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -e .
   ```

2. **Configure Environment Variables**:
   Copy `.env.example` to `.env` and fill in your details:
   ```env
   TELEGRAM_BOT_TOKEN="your_bot_token"
   TELEGRAM_ALLOWED_USER_IDS="1738119249"
   OPENCODE_BASE_URL="http://127.0.0.1:4096"
   OPENCODE_SERVER_PASSWORD="your_server_password"
   OPENCODE_SERVER_USERNAME="opencode"
   ```

3. **Configure Allowed Projects**:
   Edit `config.toml` to list the project directories you want to allow.

4. **Start OpenCode Server**:
   ```bash
   opencode serve --hostname 127.0.0.1 --port 4096
   ```

5. **Run the Bot** — any of these from the project root:
   ```bash
   ./run.sh            # run in the foreground
   make run            # same thing
   make service-start  # run as a systemd user service
   ```

## Telegram Commands

- `/start` & `/help` — Overview and command help
- `/projects` — List allowed projects
- `/project <name>` — Select working project
- `/new` — Create a new OpenCode session
- `/sessions` — List existing sessions
- `/session <id>` — Select active session
- `/models` — View available LLMs & switch model for active session
- `/agent <build|plan>` — Switch agent mode (Build or Plan)
- `/rename <title>` — Rename active session title
- `/ask <prompt>` — Submit coding task to active session
- `/status` — View server health & active task state
- `/stop` — Abort running task in active session
- `/diff` — Inspect file changes
- `/history` — View conversation history
- `/health` — Ping OpenCode server

## Day-to-day Commands

Everything runs through `make` from the project root (`make help` lists them):

| Command | What it does |
| --- | --- |
| `make install` | Install / refresh dependencies into `.venv` |
| `make run` | Run the bot in the foreground |
| `make service-start` / `-stop` / `-restart` | Control the systemd user service |
| `make service-status` | Show service status |
| `make logs` | Follow the service logs |
| `make clean` | Remove caches and build artifacts |

## Project Structure

```
opencode-bot/
├── run.sh, Makefile         # easy entry points (run / service / logs / clean)
├── config.toml              # local config (gitignored); see config.example.toml
├── .env                     # local secrets (gitignored); see .env.example
├── data/                    # SQLite state (gitignored)
├── docs/                    # idea.md (original proposal), walkthrough.md
├── systemd/                 # systemd --user unit examples
└── src/opencode_telegram/
    ├── main.py              # entry point and wiring
    ├── config.py            # env + config.toml loading
    ├── opencode/            # OpenCode V2 API layer: client, events, router, models, errors
    ├── bot/                 # Telegram layer: handlers, keyboards, notifier, callbacks, formatting, authorization
    ├── services/            # domain logic: projects, sessions, tasks, heartbeat
    └── storage/             # SQLite: database, repositories
```

