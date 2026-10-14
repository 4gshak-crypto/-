"""Настройки программы: config/settings.yaml + вебхук из окружения или .env, и журналирование."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, SecretStr

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / 'config'
INPUT_DIR = ROOT / 'input'
OUTPUT_DIR = ROOT / 'output'
LOG_DIR = OUTPUT_DIR / 'logs'

WEBHOOK_RE = re.compile(r'^https://(?P<domain>[a-z0-9.-]+)/rest/(?P<user>\d+)/(?P<key>[A-Za-z0-9]+)/?$')


class ConfigError(Exception):
    """Ошибка настройки, понятная пользователю."""


class Portal(BaseModel):
    domain: str
    entity_type_id: int
    type_id: int


class Limits(BaseModel):
    requests_per_second: float = 2
    timeout_seconds: float = 30
    max_retries: int = 5


class Tasks(BaseModel):
    third_party_responsible_last_name: str = ''


class Settings(BaseModel):
    portal: Portal
    limits: Limits = Field(default_factory=Limits)
    required_scopes: list[str] = Field(default_factory=lambda: ['crm', 'task', 'user'])
    tasks: Tasks = Field(default_factory=Tasks)
    webhook_url: SecretStr | None = None

    @property
    def uf_prefix(self) -> str:
        return f'UF_CRM_{self.portal.type_id}_'


def read_dotenv(path: Path) -> dict[str, str]:
    """Простейший разбор .env: KEY=VALUE, комментарии через #."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def load_settings(settings_path: Path | None = None, env_path: Path | None = None) -> Settings:
    settings_path = settings_path or CONFIG_DIR / 'settings.yaml'
    if not settings_path.exists():
        raise ConfigError(f'Не найден файл настроек {settings_path}')
    data = yaml.safe_load(settings_path.read_text(encoding='utf-8')) or {}
    s = Settings(**data)
    # переменная окружения важнее .env (удобно для секретов облачного окружения)
    url = os.environ.get('BITRIX_WEBHOOK_URL') or read_dotenv(env_path or ROOT / '.env').get('BITRIX_WEBHOOK_URL')
    if url:
        s.webhook_url = SecretStr(url.strip())
    return s


def validate_webhook(s: Settings) -> str:
    """Возвращает адрес вебхука, проверив формат и домен портала."""
    if s.webhook_url is None:
        raise ConfigError('Вебхук не задан. Впишите BITRIX_WEBHOOK_URL в файл .env (образец — .env.example) '
                          'или задайте переменную окружения BITRIX_WEBHOOK_URL.')
    url = s.webhook_url.get_secret_value()
    m = WEBHOOK_RE.match(url)
    if not m:
        raise ConfigError('BITRIX_WEBHOOK_URL имеет неверный вид. Нужно: https://ul-73.ru/rest/<номер>/<ключ>/')
    if m['domain'].lower() != s.portal.domain.lower():
        raise ConfigError(f'Вебхук ведёт на портал {m["domain"]}, а в config/settings.yaml указан '
                          f'{s.portal.domain}. Проверьте адрес.')
    return url if url.endswith('/') else url + '/'


class RedactFilter(logging.Filter):
    """Вырезает из сообщений журнала ключ вебхука, если он туда всё-таки попал."""

    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [x for x in secrets if x]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        changed = False
        for sec in self.secrets:
            if sec in msg:
                msg = msg.replace(sec, '***')
                changed = True
        # на всякий случай: любой вид /rest/<id>/<ключ>/
        new = re.sub(r'/rest/\d+/[A-Za-z0-9]{6,}', '/rest/***/***', msg)
        if changed or new != msg:
            record.msg, record.args = new, None
        return True


def setup_logging(settings: Settings | None = None, log_dir: Path = LOG_DIR) -> None:
    """INFO — в output/logs/app.log, ошибки дополнительно в output/logs/errors.log."""
    log_dir.mkdir(parents=True, exist_ok=True)
    secrets = []
    if settings and settings.webhook_url:
        url = settings.webhook_url.get_secret_value()
        m = WEBHOOK_RE.match(url)
        secrets = [url, m['key']] if m else [url]
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    redact = RedactFilter(secrets)
    for path, level in ((log_dir / 'app.log', logging.INFO), (log_dir / 'errors.log', logging.ERROR)):
        h = logging.FileHandler(path, encoding='utf-8')
        h.setLevel(level)
        h.setFormatter(fmt)
        h.addFilter(redact)
        root.addHandler(h)
    logging.getLogger('httpx').setLevel(logging.WARNING)  # httpx пишет полный URL — с ключом
