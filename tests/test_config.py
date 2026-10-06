from opencode_telegram.config import Config


def test_config_loads_runtime_limits(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[server]
base_url = "http://example.test:4096"
connect_timeout_seconds = 2
request_timeout_seconds = 90

[projects]
default = "work"

[projects.work]
path = "."

[bot]
progress_update_interval_seconds = 3
max_active_tasks_per_session = 1
task_timeout_seconds = 45
max_telegram_message_length = 3500
"""
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123")

    config = Config.load(config_file)

    assert config.connect_timeout_seconds == 2
    assert config.request_timeout_seconds == 90
    assert config.progress_interval_seconds == 3
    assert config.task_timeout_seconds == 45
    assert config.max_message_length == 3500