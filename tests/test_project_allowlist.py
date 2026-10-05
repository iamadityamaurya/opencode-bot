import pytest
from pathlib import Path
from opencode_telegram.config import Config, ProjectConfig
from opencode_telegram.services.projects import ProjectService

def test_project_allowlist_validation(tmp_path):
    proj_dir = tmp_path / "my_project"
    proj_dir.mkdir()
    sub_file = proj_dir / "sub" / "file.py"
    sub_file.parent.mkdir()
    sub_file.touch()

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    cfg = Config(
        telegram_token="fake_token",
        allowed_user_ids={123},
        opencode_base_url="http://127.0.0.1:4096",
        opencode_password="",
        database_path=tmp_path / "bot.sqlite3",
        log_level="INFO",
        projects={
            "my_project": ProjectConfig("my_project", proj_dir, "Test project")
        },
        default_project="my_project"
    )

    svc = ProjectService(cfg)
    # Valid paths inside project
    assert svc.validate_and_resolve_path(str(proj_dir)) == proj_dir.resolve()
    assert svc.validate_and_resolve_path(str(sub_file)) == sub_file.resolve()

    # Invalid path outside project
    with pytest.raises(ValueError, match="Access denied"):
        svc.validate_and_resolve_path(str(outside_dir))
