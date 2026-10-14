"""Командная строка: python -m bitrix_uk <команда>."""
from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.table import Table

from .client import BitrixClient, BitrixError
from .config import ConfigError, Settings, load_settings, setup_logging, validate_webhook
from .discover import run_check, run_discover, save_discovery

app = typer.Typer(help='Автоматизация смарт-процесса «Дома» в Битрикс24 (УК СВ, УК СОЮЗ, ДОМОВОЙ).',
                  no_args_is_help=True, add_completion=False)
console = Console()
log = logging.getLogger('bitrix_uk')


def _settings() -> Settings:
    try:
        s = load_settings()
    except ConfigError as e:
        console.print(f'[red]{e}[/red]')
        raise typer.Exit(2)
    setup_logging(s)
    return s


def _client(s: Settings, allow_write: bool = False) -> BitrixClient:
    try:
        url = validate_webhook(s)
    except ConfigError as e:
        console.print(f'[red]{e}[/red]')
        raise typer.Exit(2)
    return BitrixClient(url, allow_write=allow_write, requests_per_second=s.limits.requests_per_second,
                        timeout=s.limits.timeout_seconds, max_retries=s.limits.max_retries)


@app.command()
def check() -> None:
    """Проверить подключение к Битрикс24, права вебхука и смарт-процесс «Дома»."""
    s = _settings()
    log.info('check: начало')
    with _client(s) as bx:
        res = run_check(bx, s)
    t = Table(title=f'Проверка портала {s.portal.domain}')
    t.add_column('Проверка')
    t.add_column('Итог')
    t.add_column('Подробности')
    for name, ok, details in res.lines:
        t.add_row(name, f'[green]{ok}[/green]' if ok == 'да' else f'[red]{ok}[/red]', details)
    console.print(t)
    log.info('check: %s', 'всё в порядке' if res.ok else 'есть проблемы')
    raise typer.Exit(0 if res.ok else 1)


@app.command()
def discover() -> None:
    """Прочитать поля, стадии смарт-процесса и сотрудников; предложить сопоставление колонок CSV."""
    s = _settings()
    log.info('discover: начало')
    try:
        with _client(s) as bx:
            data = run_discover(bx, s)
    except BitrixError as e:
        console.print(f'[red]{e}[/red]')
        log.error('discover: %s', e)
        raise typer.Exit(1)
    path, users_path = save_discovery(data)

    t = Table(title=f'Поля смарт-процесса «{data["type_title"]}» ({data["entity_type_id"]})')
    for c in ('Код', 'UF', 'Подпись', 'Тип', 'Обяз.', 'Множ.'):
        t.add_column(c)
    for code, f in data['fields'].items():
        t.add_row(code, f['uf'], f['title'], str(f['type']), 'да' if f['required'] else '',
                  'да' if f['multiple'] else '')
    console.print(t)

    t = Table(title='Стадии')
    for c in ('Воронка', 'STATUS_ID', 'Название', 'Смысл'):
        t.add_column(c)
    for st in data['stages']:
        t.add_row(f'{st["category"]} ({st["category_id"]})', st['status_id'], st['name'], st['semantics'])
    console.print(t)

    t = Table(title='Предлагаемое сопоставление «колонка CSV → поле» (нужно ваше подтверждение)')
    for c in ('Колонка CSV', 'Поле', 'Подпись поля', 'Совпадение', 'Примечание'):
        t.add_column(c)
    colors = {'точно': 'green', 'системное': 'green', 'похоже': 'yellow', 'нет': 'red'}
    for row in data['mapping']:
        m = row['match']
        t.add_row(row['column'], row['field'] or '—', row['field_title'] or '', f'[{colors[m]}]{m}[/{colors[m]}]',
                  row['note'])
    console.print(t)
    unmatched = sum(1 for r in data['mapping'] if not r['field'])
    console.print(f'Сотрудников: {data["users_count"]} (список в {users_path.relative_to(path.parents[1])}).')
    console.print(f'Сохранено в [bold]{path.relative_to(path.parents[1])}[/bold]. Без поля: {unmatched} колонок. '
                  'Проверьте сопоставление и поставьте confirmed: true.')


def _not_yet(step: str) -> None:
    console.print(f'[yellow]Команда появится на шаге {step}: сначала подтвердите сопоставление полей '
                  'после discover.[/yellow]')
    raise typer.Exit(2)


@app.command('import-houses')
def import_houses() -> None:
    """Импорт домов из input/дома_для_импорта.csv (будет на следующем шаге)."""
    _not_yet('3')


@app.command('sync-asu-journal')
def sync_asu_journal() -> None:
    """Обработка выгрузок журнала заявок АСУ (будет на шаге 4)."""
    _not_yet('4')


@app.command()
def report() -> None:
    """Сводка в Excel и markdown (будет на шаге 4)."""
    _not_yet('4')


if __name__ == '__main__':
    app()
