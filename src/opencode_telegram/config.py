import os
import sys
import tomllib
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

@dataclass
class ProjectConfig:
    name: str
    path: Path
    description: str = ""

@dataclass
class Config:
    telegram_token: str
    allowed_user_ids: set[int]
    opencode_base_url: str
    opencode_password: str
    database_path: Path
    log_level: str
    projects: dict[str, ProjectConfig]
    default_project: str | None
    opencode_username: str = "opencode"
    progress_interval_seconds: int = 5
    max_message_length: int = 4000
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 60.0
    task_timeout_seconds: float = 600.0
    progress_edit_interval_seconds: float = 3.0
    heartbeat_interval_seconds: int = 0
    enable_reactions: bool = True

    @classmethod
    def load(cls, config_file: str | Path = "config.toml") -> "Config":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is missing or empty")

        raw_user_ids = os.getenv("TELEGRAM_ALLOWED_USER_IDS") or os.getenv("TELEGRAM_ALLOWED_CHAT_IDS") or ""
        allowed_ids = set()
        for item in raw_user_ids.split(","):
            item = item.strip()
            if item.isdigit() or (item.startswith("-") and item[1:].isdigit()):
                allowed_ids.add(int(item))

        if not allowed_ids:
            raise ValueError("No allowed Telegram user/chat IDs configured in TELEGRAM_ALLOWED_USER_IDS or TELEGRAM_ALLOWED_CHAT_IDS")

        base_url = os.getenv("OPENCODE_BASE_URL", "http://127.0.0.1:4096").rstrip("/")
        opencode_password = os.getenv("OPENCODE_SERVER_PASSWORD", os.getenv("OPENCODE_PASSWORD", "")).strip()
        opencode_username = os.getenv("OPENCODE_SERVER_USERNAME", "opencode").strip() or "opencode"

        db_path = Path(os.getenv("DATABASE_PATH", "./data/bot.sqlite3")).resolve()
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()

        config_path = Path(config_file)
        projects = {}
        default_project = None
        progress_interval = 5
        max_msg_len = 4000
        connect_timeout = 5.0
        request_timeout = 60.0
        task_timeout = 600.0
        progress_edit_interval = 3.0
        heartbeat_interval = 0
        enable_reactions = True

        if config_path.exists():
            with open(config_path, "rb") as f:
                data = tomllib.load(f)

            if "server" in data:
                server_data = data["server"]
                if "base_url" in server_data and not os.getenv("OPENCODE_BASE_URL"):
                    base_url = server_data["base_url"].rstrip("/")
                connect_timeout = float(server_data.get("connect_timeout_seconds", connect_timeout))
                request_timeout = float(server_data.get("request_timeout_seconds", request_timeout))

            if "projects" in data:
                proj_data = data["projects"]
                default_project = proj_data.get("default")
                for name, info in proj_data.items():
                    if name == "default" or not isinstance(info, dict):
                        continue
                    p_path = Path(info.get("path", "")).resolve()
                    desc = info.get("description", "")
                    projects[name] = ProjectConfig(name=name, path=p_path, description=desc)

            if "bot" in data:
                progress_interval = data["bot"].get("progress_update_interval_seconds", 5)
                max_msg_len = data["bot"].get("max_telegram_message_length", 4000)
                task_timeout = float(data["bot"].get("task_timeout_seconds", task_timeout))
                progress_edit_interval = float(
                    data["bot"].get("progress_edit_interval_seconds", progress_edit_interval)
                )
                heartbeat_interval = int(
                    data["bot"].get("heartbeat_interval_seconds", heartbeat_interval)
                )
                enable_reactions = bool(
                    data["bot"].get("enable_reactions", enable_reactions)
                )

        # Ensure default project fallback if none configured
        if not projects:
            current_repo = Path.cwd().resolve()
            projects["default"] = ProjectConfig(name="default", path=current_repo, description="Current workspace")
            default_project = "default"

        return cls(
            telegram_token=token,
            allowed_user_ids=allowed_ids,
            opencode_base_url=base_url,
            opencode_password=opencode_password,
            opencode_username=opencode_username,
            database_path=db_path,
            log_level=log_level,
            projects=projects,
            default_project=default_project,
            progress_interval_seconds=progress_interval,
            max_message_length=max_msg_len,
            connect_timeout_seconds=connect_timeout,
            request_timeout_seconds=request_timeout,
            task_timeout_seconds=task_timeout,
            progress_edit_interval_seconds=progress_edit_interval,
            heartbeat_interval_seconds=heartbeat_interval,
            enable_reactions=enable_reactions,
        )
