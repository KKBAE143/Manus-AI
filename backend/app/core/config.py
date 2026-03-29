import os
from pathlib import Path

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Manuscript Converter"
    API_V1_STR: str = "/api/v1"

    PROJECT_ROOT: str = str(Path(__file__).resolve().parents[3])
    STORAGE_ROOT: str = str(Path(__file__).resolve().parents[2] / "storage")
    DEFAULT_SQLITE_PATH: str = str(Path(__file__).resolve().parents[2] / "storage" / "manuscript_app.db")
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{(Path(__file__).resolve().parents[2] / 'storage' / 'manuscript_app.db').as_posix()}",
    )
    UPLOAD_DIR: str = str(Path(__file__).resolve().parents[2] / "storage" / "uploads")
    OUTPUT_DIR: str = str(Path(__file__).resolve().parents[2] / "storage" / "outputs")
    PROJECTS_DIR: str = str(Path(__file__).resolve().parents[2] / "storage" / "projects")

    # External APIs
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "allow"

settings = Settings()

# Ensure storage directories exist
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
os.makedirs(settings.PROJECTS_DIR, exist_ok=True)
