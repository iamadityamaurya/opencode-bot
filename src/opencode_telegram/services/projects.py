from opencode_telegram.config import Config, ProjectConfig

class ProjectService:
    def __init__(self, config: Config):
        self.config = config

    def get_allowed_projects(self) -> dict[str, ProjectConfig]:
        return self.config.projects

    def get_project(self, name: str) -> ProjectConfig | None:
        return self.config.projects.get(name)
