"""Настройки приложения. Все значения берутся из переменных окружения.

Файл `.env` рядом с проектом подхватывается автоматически, если он есть.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Минимальная загрузка .env: KEY=VALUE построчно, без зависимостей."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(PROJECT_DIR / ".env")


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass
class Settings:
    # Транскрибация (faster-whisper)
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "medium"))
    whisper_device: str = field(default_factory=lambda: _env("WHISPER_DEVICE", "auto"))
    whisper_compute_type: str = field(default_factory=lambda: _env("WHISPER_COMPUTE_TYPE", ""))
    whisper_download_root: str = field(default_factory=lambda: _env("WHISPER_DOWNLOAD_ROOT", ""))
    language: str = field(default_factory=lambda: _env("MEETING_LANGUAGE", "ru"))

    # Саммари (Claude)
    claude_model: str = field(default_factory=lambda: _env("CLAUDE_MODEL", "claude-opus-5-5"))
    claude_effort: str = field(default_factory=lambda: _env("CLAUDE_EFFORT", "high"))
    claude_max_tokens: int = field(default_factory=lambda: int(_env("CLAUDE_MAX_TOKENS", "32000")))

    # Веб-сервер и хранение результатов
    host: str = field(default_factory=lambda: _env("MEETING_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("MEETING_PORT", "8787")))
    data_dir: Path = field(
        default_factory=lambda: Path(_env("MEETING_DATA_DIR", str(PROJECT_DIR / "data")))
    )
    max_upload_mb: int = field(default_factory=lambda: int(_env("MEETING_MAX_UPLOAD_MB", "2048")))

    @property
    def has_api_key(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


settings = Settings()
