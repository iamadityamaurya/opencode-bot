# OpenCode Telegram Remote Controller

A secure, local-first Telegram bot that allows developers to remotely control an OpenCode server running on a Linux machine via Telegram.

## Features

- 🔒 **Defense-in-depth Security**: Loopback binding (`127.0.0.1`), user allowlist, and strict project path validation.
- ⚡ **Asynchronous & Non-Blocking**: Built with `asyncio`, keeping Telegram updates responsive during long AI tasks.
- 💾 **Durable State**: SQLite persistence retains active project choices, session mappings, and task state across restarts.
- 📊 **Real-time Monitoring & Control**: Check task status, view git diff summaries, and interrupt tasks remotely.
- ⚙️ **Linux Service Ready**: Configured for `systemd --user` background execution.

## Installation & Setup

1. **Clone and Install Dependencies**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/pip install -e .
   ```

2. **Configure Environment Variables**:
   Copy `.env.example` to `.env` and fill in your details:
   ```env
   TELEGRAM_BOT_TOKEN="your_bot_token"
   TELEGRAM_ALLOWED_USER_IDS="1738119249"
   OPENCODE_BASE_URL="http://127.0.0.1:4096"
   OPENCODE_SERVER_PASSWORD="your_server_password"
   ```

3. **Configure Allowed Projects**:
   Edit `config.toml` to list the project directories you want to allow.

4. **Start OpenCode Server**:
   ```bash
   opencode serve --hostname 127.0.0.1 --port 4096
   ```

5. **Run the Telegram Bot**:
   ```bash
   .venv/bin/python -m opencode_telegram.main
   ```

## Telegram Commands

- `/start` & `/help` — Overview and command help
- `/projects` — List allowed projects
- `/project <name>` — Select working project
- `/new` — Create a new OpenCode session
- `/sessions` — List existing sessions
- `/session <id>` — Select active session
- `/ask <prompt>` — Submit coding task to active session
- `/status` — View server health & active task state
- `/stop` — Abort running task in active session
- `/diff` — Inspect file changes
- `/history` — View conversation history
- `/health` — Ping OpenCode server

## Running Tests

Run unit and integration tests with `pytest`:
```bash
.venv/bin/pytest
```
