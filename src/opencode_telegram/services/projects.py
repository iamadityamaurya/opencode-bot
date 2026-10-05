from pathlib import Path
from opencode_telegram.config import Config, ProjectConfig

class ProjectService:
    def __init__(self, config: Config):
        self.config = config

    def get_allowed_projects(self) -> dict[str, ProjectConfig]:
        return self.config.projects

    def get_project(self, name: str) -> ProjectConfig | None:
        return self.config.projects.get(name)

    def validate_and_resolve_path(self, path_str: str) -> Path:
        resolved = Path(path_str).resolve()
        for proj in self.config.projects.values():
            allowed_root = proj.path.resolve()
            if resolved == allowed_root or allowed_root in resolved.parents:
                return resolved
        raise ValueError(f"Access denied: path '{path_str}' is outside allowed project directories.")
