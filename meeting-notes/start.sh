#!/usr/bin/env bash
# Запуск в один шаг для macOS и Linux: ./start.sh
# Сам создаёт окружение, ставит зависимости, спрашивает ключ при первом запуске и открывает браузер.
set -e
cd "$(dirname "$0")"

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Нужен Python 3.10 или новее. Установите с https://www.python.org/downloads/ и запустите снова."
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Создаю окружение…"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  echo "Устанавливаю зависимости (один раз, несколько минут)…"
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
  touch .venv/.installed
fi

if [ ! -f .env ]; then
  echo
  echo "Ключ Claude API нужен для составления протокола (platform.claude.com → API keys)."
  echo "Можно оставить пустым: тогда будет только расшифровка. Ключ сохранится в файле .env."
  read -r -p "ANTHROPIC_API_KEY: " key
  {
    echo "ANTHROPIC_API_KEY=$key"
    echo "# Модель распознавания речи: small (быстрее), medium (по умолчанию), large-v3 (точнее)"
    echo "# WHISPER_MODEL=medium"
  } > .env
fi

export MEETING_OPEN_BROWSER=1
echo
echo "Запускаю. Остановить: Ctrl+C."
exec python -m meeting_notes
