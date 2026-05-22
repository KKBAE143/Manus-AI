import os
from pathlib import Path

from pydantic_settings import BaseSettings


_SOURCE_DEFAULT_STORAGE = Path(__file__).resolve().parents[2] / "storage"


class Settings(BaseSettings):
    PROJECT_NAME: str = "Manuscript Converter"
    API_V1_STR: str = "/api/v1"

    PROJECT_ROOT: str = str(Path(__file__).resolve().parents[3])
    # STORAGE_ROOT can be overridden via env var (e.g. /var/data/storage on
    # the production VM, where it's a mounted persistent volume).
    STORAGE_ROOT: str = os.environ.get(
        "STORAGE_ROOT", str(_SOURCE_DEFAULT_STORAGE)
    )

    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{(Path(os.environ.get('STORAGE_ROOT', str(_SOURCE_DEFAULT_STORAGE))) / 'manuscript_app.db').as_posix()}",
    )

    # External APIs
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")

    @property
    def DEFAULT_SQLITE_PATH(self) -> str:
        return str(Path(self.STORAGE_ROOT) / "manuscript_app.db")

    @property
    def UPLOAD_DIR(self) -> str:
        return str(Path(self.STORAGE_ROOT) / "uploads")

    @property
    def OUTPUT_DIR(self) -> str:
        return str(Path(self.STORAGE_ROOT) / "outputs")

    @property
    def PROJECTS_DIR(self) -> str:
        return str(Path(self.STORAGE_ROOT) / "projects")

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "allow"


settings = Settings()

# Ensure storage directories exist
os.makedirs(settings.STORAGE_ROOT, exist_ok=True)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
os.makedirs(settings.PROJECTS_DIR, exist_ok=True)
