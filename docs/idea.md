# OpenCode Telegram Remote Controller

## Project Idea, Product Requirements, Architecture, and Implementation Plan

**Project type:** Local-first developer tool\
**Primary platform:** Linux\
**Core technologies:** OpenCode CLI/server, Python, Telegram Bot API,
HTTP, Server-Sent Events (SSE), systemd\
**Project status:** Technical implementation proposal\
**Audience:** An AI coding agent implementing the project

------------------------------------------------------------------------

## 1. Project overview

Build a secure Telegram bot that allows its owner to remotely interact
with OpenCode running on their Linux machine.

The user should be able to open Telegram on a phone or another computer,
send a coding task, and have the local OpenCode instance work in a
selected project directory. The bot should return responses, task
status, errors, and useful notifications. It should support persistent
OpenCode sessions so follow-up prompts retain conversation context.

The project should wrap OpenCode rather than fork or modify it. Prefer
OpenCode's documented HTTP server API for session-oriented work.
Optionally add a separate terminal/TUI control mode later for users who
specifically need to interact with an already-running interactive CLI.

### Core user story

> As the owner of a Linux machine, I want to message my Telegram bot to
> start or continue an OpenCode session in one of my allowed project
> directories, submit coding tasks, inspect progress and changes, and
> stop work remotely---without exposing an unauthenticated OpenCode
> server to the internet.

### Important distinction

There are two different use cases:

1.  **Remote OpenCode session control (recommended MVP):** The bot
    communicates with the OpenCode headless server through its HTTP API.
    This is suitable for creating sessions, sending prompts, reading
    responses, checking status, aborting work, and inspecting diffs.
2.  **Control of an existing interactive terminal/TUI (optional advanced
    feature):** The bot controls a terminal process, for example through
    `tmux`, or uses documented TUI endpoints when a TUI is connected.
    This is not the same as controlling a headless API session. Avoid
    pretending terminal screen scraping is a reliable API.

The MVP should implement use case 1 first.

------------------------------------------------------------------------

## 2. Goals

-   Send prompts to a local OpenCode server from Telegram.
-   Create, select, and continue OpenCode sessions.
-   Keep session context across bot restarts.
-   Support more than one configured project, with strict path
    allowlisting.
-   Return useful assistant responses to Telegram.
-   Handle long-running tasks without blocking the bot.
-   Provide task status, cancellation, and change summaries.
-   Send completion and error notifications.
-   Authenticate Telegram users using an explicit numeric user-ID
    allowlist.
-   Run as a background service on Linux using `systemd`.
-   Keep the OpenCode server bound to localhost by default.
-   Make failures observable through logs and useful Telegram messages.

## 3. Non-goals for the MVP

-   Reimplementing OpenCode's agent, model, tool execution, or
    permission system.
-   Exposing an arbitrary shell to Telegram.
-   Publicly exposing the OpenCode HTTP API.
-   Supporting multiple unrelated Telegram users or a public hosted bot.
-   Reliably parsing arbitrary terminal screen output.
-   Automatically approving every OpenCode permission request.
-   Building a web dashboard before the Telegram workflow is reliable.

------------------------------------------------------------------------

## 4. Proposed architecture

``` text
                  Telegram client
                 (phone / desktop)
                         |
                         | Telegram Bot API
                         | long polling (outbound)
                         v
              +-----------------------+
              | Telegram bot process  |
              | Python                |
              |                       |
              | - User authorization |
              | - Commands / buttons |
              | - Session selection   |
              | - Task orchestration  |
              | - Message formatting  |
              +-----------+-----------+
                          |
                          | HTTP on loopback
                          v
              +-----------------------+
              | OpenCode server      |
              | 127.0.0.1:4096       |
              |                       |
              | - Projects            |
              | - Sessions            |
              | - Prompts             |
              | - Events              |
              | - Permissions         |
              +-----------+-----------+
                          |
                          v
              +-----------------------+
              | Allowed project       |
              | directories           |
              |                       |
              | source code / files   |
              +-----------------------+
```

### Components

**Telegram bot** - Receives commands and text messages. - Checks the
sender's Telegram numeric user ID before doing anything. - Maps Telegram
chat/user to the selected project and OpenCode session. - Sends prompts
and status updates. - Handles callback buttons for actions such as
cancel or permission decisions.

**OpenCode server** - Runs locally on the Linux host. - Is started with
a known project working directory or otherwise explicitly selects a
project through the API. - Provides session and prompt APIs. - Emits
server events that can be consumed for progress and completion
tracking. - Is not directly exposed to the public internet.

**Persistence layer** - SQLite is recommended for the first robust
version. - Stores configured projects, Telegram user's active
project/session, task state, timestamps, and mapping of Telegram
messages to OpenCode tasks. - Never store the Telegram bot token in the
database. - Use transactions and unique identifiers to prevent duplicate
task records.

**Process/service management** - `systemd --user` can manage the bot and
OpenCode server. - The bot should reconnect/retry if the OpenCode server
restarts. - Logs should go to stdout/stderr so journald can collect
them.

------------------------------------------------------------------------

## 5. Recommended technology choices

  -----------------------------------------------------------------------
  Area                    Choice                  Reason
  ----------------------- ----------------------- -----------------------
  Language                Python 3                Good async ecosystem
                                                  and easy local
                                                  deployment

  Telegram                `python-telegram-bot`   Async handlers,
                                                  commands, callback
                                                  queries, polling

  HTTP client             `httpx`                 Async HTTP calls and
                                                  streaming support

  Configuration           `python-dotenv` for     Keep secrets out of
                          development;            source control
                          environment variables   
                          in service              

  Persistence             SQLite (`sqlite3` or    Local, simple, durable
                          `aiosqlite`)            session mapping

  Event stream            SSE using HTTP          OpenCode event updates
                          streaming               

  Service manager         systemd user services   Restart on failure and
                                                  boot startup

  Optional terminal mode  tmux                    Persistent terminal
                                                  process; separate from
                                                  API mode

  Tests                   pytest +                Test without a live
                          pytest-asyncio + mocked model for most logic
                          HTTP                    
  -----------------------------------------------------------------------

Pin compatible dependency versions in a requirements file or use a
lockfile. Check current library documentation before relying on a
particular method signature.

------------------------------------------------------------------------

## 6. OpenCode integration

### 6.1 Start the server

Example:

``` bash
cd /path/to/allowed/project
opencode serve --hostname 127.0.0.1 --port 4096
```

Use the installed `opencode` executable path in systemd. Do not bind to
`0.0.0.0` for the default local-only deployment.

Health check:

``` bash
curl http://127.0.0.1:4096/global/health
```

Open the API documentation served by the running instance:

``` text
http://127.0.0.1:4096/doc
```

The implementation must treat the installed server's `/doc` schema as
authoritative. OpenCode API details can evolve. Verify request bodies,
response shapes, authentication behavior, and event payloads against the
version actually installed before coding the integration.

### 6.2 API operations to investigate/use

The following are useful documented API routes in OpenCode's server API.
Verify each route and its exact schema in the local `/doc` before
implementation.

  ------------------------------------------------------------------------------------------
  Operation               Method and route                           Purpose
  ----------------------- ------------------------------------------ -----------------------
  Health                  `GET /global/health`                       Check server
                                                                     availability

  Projects                `GET /project`                             Discover projects if
                                                                     needed

  Sessions                `GET /session`                             List sessions

  Create session          `POST /session`                            Create a conversation

  Send and wait           `POST /session/{sessionID}/message`        Submit a prompt and
                                                                     await response

  Send asynchronously     `POST /session/{sessionID}/prompt_async`   Start a prompt without
                                                                     waiting for completion

  Message history         `GET /session/{sessionID}/message`         Retrieve conversation
                                                                     history

  Abort                   `POST /session/{sessionID}/abort`          Request cancellation

  Session status          `GET /session/status`                      Query session status

  Diff                    `GET /session/{sessionID}/diff`            Inspect changes for a
                                                                     session

  Events                  `GET /event`                               Subscribe to server
                                                                     events

  TUI append prompt       `POST /tui/append-prompt`                  Append text to a
                                                                     connected TUI prompt

  TUI submit prompt       `POST /tui/submit-prompt`                  Submit prompt in a
                                                                     connected TUI

  TUI clear prompt        `POST /tui/clear-prompt`                   Clear connected TUI
                                                                     prompt

  TUI execute command     `POST /tui/execute-command`                Execute a TUI command
  ------------------------------------------------------------------------------------------

Use session API endpoints for the MVP. TUI endpoints should be
considered only when a TUI is actually connected and the intended
behavior is verified.

### 6.3 Prompt payloads and responses

Do not assume the response from a prompt endpoint is always a plain
string. OpenCode messages may contain multiple parts, including text and
tool-related information. Implement a response adapter that: - validates
the response shape; - extracts user-readable text parts; - handles empty
responses; - avoids exposing internal tool payloads or secrets; -
preserves useful error information in logs.

Do not send raw, unbounded server JSON to Telegram.

### 6.4 Session lifecycle

A session should be associated with a project. Store at least: -
OpenCode session ID; - project ID/path; - Telegram user ID; - Telegram
chat ID; - human-readable title; - created/updated timestamps; - whether
it is selected/archived, if supported by the UX.

Support: - create session; - list sessions; - select session; - continue
session; - create a new session; - optionally rename/archive session if
supported by the current API.

Do not assume a session is still valid after server restarts without
checking it.

------------------------------------------------------------------------

## 7. Telegram command design

Use a clear command interface. The final names can be adjusted, but
preserve the functionality.

  -----------------------------------------------------------------------
  Command                             Behavior
  ----------------------------------- -----------------------------------
  `/start`                            Explain the bot and show available
                                      commands

  `/help`                             Show help

  `/projects`                         List configured/allowed projects

  `/project <name>`                   Select an allowed project

  `/new`                              Create a session in the selected
                                      project

  `/sessions`                         List sessions for the selected
                                      project

  `/session <id>`                     Select a session

  `/ask <prompt>`                     Submit a prompt to the selected
                                      session

  Plain text                          Optional: treat as a prompt only
                                      when a session is selected

  `/status`                           Show active task and session state

  `/stop`                             Abort active task after validating
                                      its session

  `/history`                          Show recent conversation messages

  `/diff`                             Summarize changed files for the
                                      selected session

  `/health`                           Check OpenCode server and bot state

  `/cancel`                           Cancel a Telegram-side pending
                                      interaction, if applicable
  -----------------------------------------------------------------------

### UX expectations

-   `/start` should explain that the bot controls the local machine's
    OpenCode instance.
-   If no project is selected, explain how to select one.
-   If no session is selected, offer `/new`.
-   If a task is already running, do not silently start a conflicting
    task.
-   When a task begins, immediately acknowledge it and provide a task
    identifier.
-   When it completes, send a concise result and optionally a diff
    summary.
-   On failure, send a concise user-facing error and log technical
    details locally.
-   Use Telegram inline buttons for common actions: Stop, View diff, New
    session, and Select session.
-   Support Telegram message length limits by splitting output safely,
    preferably at paragraph/code-block boundaries.
-   Escape Markdown/HTML correctly or use plain text to avoid formatting
    failures.

------------------------------------------------------------------------

## 8. Task orchestration and concurrency

A key design requirement is to separate Telegram update handling from
long-running OpenCode work.

### Recommended task flow

1.  Validate the Telegram sender.
2.  Parse the command and resolve the selected project/session.
3.  Check whether another task is already active for that session.
4.  Create a durable task record with state `queued` or `running`.
5.  Send an immediate Telegram acknowledgment.
6.  Submit the prompt to OpenCode using the verified async endpoint.
7.  Track OpenCode events and/or poll session status/history as a
    fallback.
8.  When the assistant turn is complete, retrieve the final message.
9.  Update the task record to `completed`, `failed`, or `cancelled`.
10. Send a completion notification and relevant summary.

### Concurrency policy

For the MVP: - Allow at most one active prompt per OpenCode session. -
Optionally allow one active task per project to avoid overlapping file
edits. - Use an `asyncio.Lock` for in-process coordination, but do not
rely on it as the only protection if multiple bot processes could run. -
Use SQLite state/transactions or a database constraint for durable task
uniqueness. - Prevent duplicate processing of the same Telegram update
where practical. - Do not let `/stop` cancel an unrelated session.

### Cancellation

Cancellation should: - identify the exact active task and OpenCode
session; - call the documented abort endpoint; - report that
cancellation was requested, not claim it succeeded prematurely; - await
a terminal state/event or verify status before marking the task
cancelled; - handle races where the task finishes just before abort is
sent.

### Async prompt versus synchronous prompt

For a quick prototype, the synchronous message endpoint is simpler. For
a durable bot, prefer the async prompt endpoint plus event tracking. Do
not block the Telegram event loop while waiting for long model calls.

------------------------------------------------------------------------

## 9. Event streaming and progress

Use the OpenCode event endpoint (`GET /event`) if supported by the
installed version. It is an SSE stream; confirm the exact event schema
in `/doc`.

Implementation requirements: - Maintain one event listener per OpenCode
server, not one per Telegram message. - Reconnect with exponential
backoff after connection loss. - Parse SSE frames correctly (`event`,
`data`, blank-line delimiters); do not assume each network chunk is one
complete event. - Filter events by project/session/task where
possible. - Ignore unknown event types safely. - Log event types and
correlation identifiers, but avoid logging secrets or full private
prompts by default. - Handle server restarts and stale session IDs. -
Provide a polling fallback for task completion if the event stream
disconnects.

### Telegram progress strategy

Avoid sending a Telegram message for every token or low-level event.
This can overwhelm the chat and hit Telegram rate limits.

Prefer: - one initial "Task started" message; - occasional meaningful
progress updates (e.g. started, tool activity, awaiting permission,
completed); - one final summary; - an optional `/status` command for
on-demand detail.

Progress messages should be throttled and coalesced.

------------------------------------------------------------------------

## 10. Security requirements

This tool can cause an AI coding agent to read and modify local files
and run tools. Security must be part of the initial design.

### Mandatory safeguards

1.  **Telegram allowlist:** Only accept messages from configured numeric
    Telegram user IDs. Check every command and callback query.
2.  **Loopback binding:** Bind OpenCode to `127.0.0.1`, not a public
    interface, by default.
3.  **No arbitrary shell command feature in MVP:** Do not implement
    `/shell <command>` or pass Telegram text to
    `subprocess(..., shell=True)`.
4.  **Project allowlist:** Permit only explicitly configured project
    directories. Resolve symlinks and verify the resolved path is within
    an allowed root before selecting it.
5.  **Secret handling:** Keep the Telegram token in an environment file
    with restrictive permissions or a secret manager. Never commit it.
6.  **Permission prompts:** Preserve OpenCode's permission model. Do not
    automatically approve all tool requests.
7.  **Callback validation:** Treat callback data as untrusted. Validate
    user, chat, session, permission ID, and task state.
8.  **HTTP timeouts:** Set connection and read timeouts. Handle
    disconnects and cancellation.
9.  **Output hygiene:** Avoid sending environment variables,
    credentials, private keys, or sensitive tool output to Telegram.
    Consider a redaction layer.
10. **Logs:** Do not log bot tokens, authorization headers, or secrets.
    Make prompt logging opt-in.
11. **Rate limits:** Limit prompt frequency and prevent accidental
    duplicate submissions.
12. **Local access:** The bot should be the only intended client of the
    local API. If the OpenCode server supports authentication, configure
    it as defense in depth, while retaining loopback binding.

### Threat model

Assume: - a Telegram account may be compromised; - the bot token may
leak; - messages may be duplicated or arrive out of order; - the laptop
may sleep or lose connectivity; - OpenCode may crash or restart; - a
model may request risky actions; - a project may contain secrets.

The bot should fail closed when authorization or project resolution is
uncertain.

------------------------------------------------------------------------

## 11. Configuration

Use environment variables for secrets and a separate config file for
non-secret project definitions.

Example `.env`:

``` dotenv
TELEGRAM_BOT_TOKEN=replace_me
TELEGRAM_ALLOWED_USER_IDS=123456789
OPENCODE_BASE_URL=http://127.0.0.1:4096
DATABASE_PATH=./data/bot.sqlite3
LOG_LEVEL=INFO
```

Example `config.toml`:

``` toml
[server]
base_url = "http://127.0.0.1:4096"
connect_timeout_seconds = 5
request_timeout_seconds = 600

[projects]
default = "my-project"

[projects.my-project]
path = "/home/your-user/code/my-project"

[projects.another-project]
path = "/home/your-user/code/another-project"

[bot]
max_active_tasks_per_session = 1
progress_update_interval_seconds = 10
max_telegram_message_length = 4000
```

Validate all configuration at startup. Do not silently fall back to an
arbitrary current working directory.

------------------------------------------------------------------------

## 12. Suggested repository structure

``` text
opencode-telegram/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── config.example.toml
├── src/
│   └── opencode_telegram/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── bot/
│       │   ├── handlers.py
│       │   ├── keyboards.py
│       │   ├── authorization.py
│       │   └── formatting.py
│       ├── opencode/
│       │   ├── client.py
│       │   ├── models.py
│       │   ├── events.py
│       │   └── errors.py
│       ├── services/
│       │   ├── sessions.py
│       │   ├── tasks.py
│       │   └── projects.py
│       └── storage/
│           ├── database.py
│           └── repositories.py
├── tests/
│   ├── test_authorization.py
│   ├── test_commands.py
│   ├── test_opencode_client.py
│   ├── test_task_lifecycle.py
│   └── test_project_allowlist.py
├── systemd/
│   ├── opencode-server.service.example
│   └── opencode-telegram.service.example
└── data/
    └── .gitkeep
```

The agent may simplify this structure for the MVP, but should keep
Telegram handlers, OpenCode API access, configuration, and persistence
logically separated.

------------------------------------------------------------------------

## 13. Implementation milestones

### Milestone 1 --- Verify local OpenCode API

-   Check that `opencode` is installed.
-   Start `opencode serve` on loopback.
-   Check `/global/health`.
-   Open `/doc`.
-   Verify session creation, prompt request, response shape, abort,
    status, and diff routes against the installed version.
-   Record any version-specific differences.

**Acceptance criteria:** A local script can create a session, send a
prompt, and print the readable response.

### Milestone 2 --- Minimal Telegram bot

-   Create bot with BotFather.
-   Add configuration loading.
-   Implement strict user allowlist.
-   Implement `/start`, `/help`, `/new`, `/ask`.
-   Use an OpenCode API client class rather than scattering HTTP calls
    through handlers.
-   Handle HTTP errors and timeouts.

**Acceptance criteria:** The authorized Telegram user can create a
session and receive an OpenCode response.

### Milestone 3 --- Durable sessions

-   Add SQLite schema and migrations.
-   Store project/session selection per Telegram user/chat.
-   Add `/projects`, `/project`, `/sessions`, and `/session`.
-   Restore selected session after bot restart.
-   Validate stored sessions against the server when needed.

**Acceptance criteria:** Restarting the bot does not lose the user's
selected project/session.

### Milestone 4 --- Task lifecycle

-   Add durable task records.
-   Implement async prompt submission.
-   Track task states: `queued`, `running`, `awaiting_permission`,
    `completed`, `failed`, `cancel_requested`, `cancelled`, `unknown`.
-   Implement `/status` and `/stop`.
-   Ensure only one active task per session.
-   Handle duplicate messages and API timeouts.

**Acceptance criteria:** Long tasks do not block unrelated Telegram
commands; stop targets only the correct task/session.

### Milestone 5 --- Events and notifications

-   Implement a resilient SSE listener.
-   Parse event frames correctly.
-   Correlate events to sessions/tasks.
-   Send throttled progress updates.
-   Send final response and optional diff summary.
-   Add polling fallback if the event connection fails.

**Acceptance criteria:** A long task can finish and notify Telegram even
if the event stream briefly disconnects.

### Milestone 6 --- Permission workflow

-   Detect permission requests from the documented event/API behavior.
-   Send inline Approve/Deny buttons.
-   Validate callback ownership and request freshness.
-   Call the documented permission response endpoint.
-   Handle expired or already-resolved permission requests.

**Acceptance criteria:** A permission request can be safely approved or
denied only by the authorized user.

### Milestone 7 --- Linux service

-   Add example systemd user units.
-   Use absolute executable paths and explicit working directories.
-   Configure restart behavior and journald logging.
-   Document how to start, stop, restart, and inspect logs.
-   Document lingering if operation after logout is desired.

**Acceptance criteria:** After reboot/login conditions are configured,
the server and bot start automatically and recover from process
failures.

### Milestone 8 --- Optional TUI/tmux mode

Only after the API mode is stable: - Determine whether the requirement
is to control a TUI connected to the server or to control a terminal
process. - If using `tmux`, create a dedicated named session and launch
OpenCode inside it. - Restrict which tmux session/window can be
controlled. - Avoid accepting arbitrary terminal escape sequences or
arbitrary shell commands from Telegram. - Treat captured terminal output
as untrusted and potentially truncated. - Keep TUI mode clearly separate
from API session mode.

**Acceptance criteria:** The user can attach locally to the same tmux
session and see the terminal that the bot controls.

------------------------------------------------------------------------

## 14. Testing plan

Use mocked HTTP responses for most unit tests. Live OpenCode/model tests
should be opt-in because they may consume API credits or take a long
time.

### Unit tests

-   Unauthorized user cannot run any command.
-   Unauthorized callback query is ignored/rejected.
-   Missing project/session produces a helpful response.
-   Invalid project paths and symlink escapes are rejected.
-   API error response is handled safely.
-   Telegram message splitting stays within the configured limit.
-   Empty OpenCode response is handled.
-   Session selection persists across process restart.
-   A second prompt cannot race into the same session while one is
    active.
-   `/stop` aborts only the matching active session.
-   Stale permission buttons cannot approve an old request.

### Integration tests

-   Start a local OpenCode server.
-   Verify health endpoint.
-   Create a session.
-   Send a simple prompt.
-   Read response/history.
-   Verify diff endpoint behavior.
-   Test abort on a deliberately long-running task.
-   Test server restart while the bot is running.
-   Test SSE disconnect/reconnect.

### Manual acceptance test

1.  Start the server and bot.
2.  Send `/start`.
3.  Select a project.
4.  Create a session.
5.  Ask OpenCode to create a small file.
6.  Confirm the file appears in the project.
7.  Ask for a modification in the same session.
8.  Check `/status` and `/diff`.
9.  Test `/stop` on a longer task.
10. Restart the bot and confirm the session can be resumed.
11. Send a message from an unauthorized Telegram account and confirm it
    is rejected.

------------------------------------------------------------------------

## 15. Error handling and reliability

Implement explicit handling for: - OpenCode server unavailable; - server
starts slowly; - connection timeout; - request timeout; - HTTP
4xx/5xx; - malformed or unexpected API response; - invalid/stale
session; - session busy; - task abort race; - SSE disconnect; - Telegram
rate limit (`RetryAfter`); - Telegram message too long; - SQLite
busy/locked; - bot restart during an active task.

For uncertain outcomes, do not automatically resubmit a prompt: a
timeout can happen after OpenCode accepted the request. First reconcile
against session history/status or mark the task `unknown` and tell the
user.

Use bounded retries with backoff for safe operations such as health
checks and event reconnection. Avoid blindly retrying prompt
submissions.

------------------------------------------------------------------------

## 16. UX details

### `/status`

Show: - selected project; - session ID (shortened for display); - active
task ID and state; - whether OpenCode server is reachable; - last update
time.

### `/diff`

Return a concise list of changed files and additions/deletions. Offer a
separate command or button to retrieve a bounded patch if supported and
safe. Do not flood Telegram with huge diffs.

### `/history`

Return a bounded number of recent messages. Avoid exposing internal tool
arguments, environment values, or secret-bearing output.

### Task notifications

Example:

``` text
Task started
Project: my-project
Session: ses_...
Task: task_...

OpenCode is working. Use /status to check progress
or /stop to request cancellation.
```

Completion example:

``` text
Task completed
Project: my-project
Summary: Added login form validation.
Changed files: 3
Use /diff to inspect the changes.
```

These are illustrative formats; generate the summary from actual
response data rather than hardcoding success.

------------------------------------------------------------------------

## 17. Documentation and reference links

Use these official resources as the primary sources. The implementation
agent should read the current pages and inspect the local API schema
before coding.

### OpenCode

-   **Server documentation:** https://opencode.ai/docs/server/
-   **CLI documentation:** https://opencode.ai/docs/cli/
-   **OpenCode documentation home:** https://opencode.ai/docs/
-   **OpenCode source repository:**
    https://github.com/anomalyco/opencode
-   **OpenCode API schema:** `http://127.0.0.1:4096/doc` after starting
    the local server

### Telegram

-   **Telegram Bot API:** https://core.telegram.org/bots/api
-   **Telegram Bot features / commands:**
    https://core.telegram.org/bots/features
-   **BotFather:** https://t.me/BotFather
-   **python-telegram-bot documentation:**
    https://docs.python-telegram-bot.org/
-   **python-telegram-bot GitHub:**
    https://github.com/python-telegram-bot/python-telegram-bot

### Python and supporting libraries

-   **Python venv:** https://docs.python.org/3/library/venv.html
-   **HTTPX:** https://www.python-httpx.org/
-   **python-dotenv:** https://github.com/theskumar/python-dotenv
-   **SQLite:** https://www.sqlite.org/docs.html
-   **pytest:** https://docs.pytest.org/
-   **pytest-asyncio:** https://pytest-asyncio.readthedocs.io/

### Linux service management

-   **systemd documentation:**
    https://www.freedesktop.org/software/systemd/man/
-   **systemd service unit:**
    https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
-   **systemd user services:**
    https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html
-   **loginctl / lingering:**
    https://www.freedesktop.org/software/systemd/man/latest/loginctl.html
-   **tmux manual:** https://man.openbsd.org/tmux.1

### Protocol references

-   **Server-Sent Events:**
    https://html.spec.whatwg.org/multipage/server-sent-events.html
-   **HTTP semantics:** https://www.rfc-editor.org/rfc/rfc9110

------------------------------------------------------------------------

## 18. Instructions for the AI coding agent

Implement this project in the current repository or create a new
repository if none exists.

Before writing integration code:

1.  Inspect the local environment and determine whether OpenCode is
    installed.
2.  Read the current official OpenCode server and CLI documentation.
3.  If a local OpenCode server can be started, inspect
    `http://127.0.0.1:4096/doc` and use its actual schemas.
4.  Do not invent API routes, event names, request fields, or response
    fields.
5.  If the API schema differs from this proposal, adapt the
    implementation to the installed version and document the difference.
6.  Ask before making destructive changes to existing project files or
    system configuration.

Implementation expectations:

-   Build a maintainable Python application with clear module
    boundaries.
-   Start with a working minimal end-to-end flow: Telegram `/start`,
    `/new`, `/ask`, and response.
-   Add persistence, async tasks, event streaming, cancellation,
    permissions, and systemd in incremental steps.
-   Keep secrets out of source control.
-   Include `.env.example`, example configuration, setup instructions,
    and troubleshooting.
-   Add tests for authorization, session mapping, API client behavior,
    and task state transitions.
-   Do not claim a feature works until it has been implemented and
    tested.
-   Prefer documented APIs over terminal scraping.
-   Do not add arbitrary remote shell execution.
-   Keep the OpenCode API bound to loopback unless the owner explicitly
    requests and understands a different deployment.
-   Report assumptions, files changed, commands run, tests, and any
    remaining limitations at the end.

### Definition of done for the first usable release

The first usable release is complete when: - the bot starts locally and
connects to Telegram; - only the configured Telegram user can control
it; - it can create an OpenCode session; - it can send a prompt and
return the response; - it can resume the selected session after a bot
restart; - it can show status and request cancellation; - it documents
installation, configuration, startup, and troubleshooting; - automated
tests cover core authorization and API-client behavior.

Do not attempt to implement every advanced feature in one pass. Deliver
a working MVP first, then continue through the milestones.
