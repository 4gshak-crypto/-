@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Протокол совещания

where python >nul 2>nul
if errorlevel 1 (
    echo Нужен Python 3.10 или новее. Установите с https://www.python.org/downloads/
    echo и при установке поставьте галочку "Add Python to PATH". Затем запустите снова.
    pause
    exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>nul
if errorlevel 1 (
    echo Установлен слишком старый Python. Нужен 3.10 или новее: https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Создаю окружение...
    python -m venv .venv
    if errorlevel 1 ( pause & exit /b 1 )
)
call ".venv\Scripts\activate.bat"

if not exist ".venv\.installed" (
    echo Устанавливаю зависимости ^(один раз, несколько минут^)...
    python -m pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
    if errorlevel 1 (
        echo Не удалось установить зависимости. Проверьте интернет и запустите снова.
        pause
        exit /b 1
    )
    echo ok> ".venv\.installed"
)

if not exist ".env" (
    echo.
    echo Ключ Claude API нужен для составления протокола ^(platform.claude.com, раздел API keys^).
    echo Можно оставить пустым: тогда будет только расшифровка. Ключ сохранится в файле .env.
    set /p key="ANTHROPIC_API_KEY: "
    (
        echo ANTHROPIC_API_KEY=%key%
        echo # Модель распознавания речи: small ^(быстрее^), medium ^(по умолчанию^), large-v3 ^(точнее^)
        echo # WHISPER_MODEL=medium
    ) > .env
)

set MEETING_OPEN_BROWSER=1
echo.
echo Запускаю. Не закрывайте это окно, пока работаете с приложением. Остановить: Ctrl+C.
python -m meeting_notes
pause
