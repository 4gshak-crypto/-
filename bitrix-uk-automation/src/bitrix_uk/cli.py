"""Командная строка: python -m bitrix_uk <команда>."""
from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .asu import AsuFormatError, classify, find_repeats, load_rules, read_journals
from .client import BitrixClient, BitrixError
from .config import CONFIG_DIR, INPUT_DIR, ConfigError, Settings, load_settings, setup_logging, validate_webhook
from .discover import run_check, run_discover, save_discovery
from .houses import house_refs, read_houses_csv
from .matching import HouseIndex, load_aliases

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


def _table(title: str, columns: list[str], rows: list[list[str]], limit: int) -> None:
    t = Table(title=f'{title}: {len(rows)}')
    for c in columns:
        t.add_column(c, overflow='fold')
    for r in rows[:limit]:
        t.add_row(*r)
    console.print(t)
    if len(rows) > limit:
        console.print(f'  … и ещё {len(rows) - limit} (покажите больше: --limit {len(rows)})')


@app.command('asu-preview')
def asu_preview(
    path: Path = typer.Argument(None, help='файл или папка с выгрузками АСУ; по умолчанию input/asu'),
    houses: Path = typer.Option(None, '--houses', help='реестр домов CSV; по умолчанию input/дома_для_импорта.csv'),
    limit: int = typer.Option(30, help='сколько строк показывать в каждой таблице'),
) -> None:
    """Разобрать журнал заявок АСУ без Битрикса: аварии, третьи стороны, «не выполнено», повторы, адреса."""
    s = _settings()
    path = path or INPUT_DIR / 'asu'
    files = sorted(path.glob('*.xlsx')) if path.is_dir() else [path]
    files = [f for f in files if not f.name.startswith('~$')]
    if not files:
        console.print(f'[red]Нет выгрузок АСУ (*.xlsx) в {path}[/red]')
        raise typer.Exit(2)
    try:
        requests, journals = read_journals(files)
    except AsuFormatError as e:
        console.print(f'[red]{e}[/red]')
        raise typer.Exit(1)
    rules = load_rules()

    houses = houses or INPUT_DIR / 'дома_для_импорта.csv'
    index = None
    if houses.exists():
        index = HouseIndex(house_refs(read_houses_csv(houses)), load_aliases(CONFIG_DIR / 'address_aliases.yaml'))
    matches = {raw: index.match(raw) for raw in {r.house for r in requests}} if index else {}

    items = []
    for r in requests:
        c = classify(r, rules)
        m = matches.get(r.house)
        items.append((r, c, m.house.id if m and m.found else r.house.lower()))

    for j in journals:
        period = f'{j.period[0]:%d.%m.%Y %H:%M} — {j.period[1]:%d.%m.%Y %H:%M}' if j.period else 'не указан'
        console.print(f'Файл {j.path.name}: заявок {len(j.requests)}, период {period}')
        for w in j.warnings:
            console.print(f'  [yellow]{w}[/yellow]')
    console.print(f'Всего заявок (без повторов между файлами): {len(requests)}, домов: {len({r.house for r in requests})}')
    console.print('По статусам: ' + ', '.join(f'{k or "—"} {v}' for k, v in Counter(r.status for r in requests).most_common()))

    fmt = lambda d: f'{d:%d.%m %H:%M}'  # noqa: E731
    _table('Аварии', ['№', 'Создана', 'Дом', 'Система', 'Причина', 'Статус'],
           [[str(r.number), fmt(r.created_at), r.house, c.system or '—', ', '.join(c.critical_reasons), r.status]
            for r, c, _ in items if c.critical], limit)
    _table('Третья сторона (задача ответственному)', ['№', 'Дом', 'Кому', 'Передано', 'Откуда время', 'Комментарий'],
           [[str(r.number), r.house, c.recipient or '[yellow]не определено[/yellow]', fmt(c.handed_at),
             c.handed_at_source, r.comment_text[:80]] for r, c, _ in items if c.third_party], limit)
    _table('Жилец ответил «Не выполнено» (задача мастеру)', ['№', 'Дом', 'Тип', 'Исполнитель', 'Статус'],
           [[str(r.number), r.house, r.type or '—', r.executor or '—', r.status]
            for r, c, _ in items if r.not_done_by_resident], limit)
    reps = find_repeats(items, rules)
    _table(f'Повторяющиеся проблемы (≥{rules.repeat_min} заявок за {rules.repeat_days} дней)',
           ['Дом', 'Система', 'Заявок', 'Номера', 'Период'],
           [[x.house, x.system, str(len(x.numbers)), ', '.join(map(str, x.numbers[:8])),
             f'{x.first:%d.%m}–{x.last:%d.%m}'] for x in reps], limit)
    no_system = sum(1 for _, c, _ in items if not c.system)
    console.print(f'Система не определена: {no_system} заявок (дополните config/asu_rules.yaml).')

    if index is None:
        console.print(f'[yellow]Реестр домов {houses.name} не найден — адреса не проверены. '
                      'Положите CSV в input/ или укажите --houses.[/yellow]')
    else:
        stat = Counter(m.status for m in matches.values())
        names = {'found': 'найдено', 'ambiguous': 'неоднозначно', 'needs_review': 'на проверку', 'not_found': 'не найдено'}
        console.print('Адреса домов из журнала: ' + ', '.join(f'{names[k]} {v}' for k, v in stat.most_common()))
        _table('Адреса, которые нужно проверить', ['Адрес в АСУ', 'Итог', 'Кандидаты'],
               [[raw, names[m.status], '; '.join(f'{c.house.title} ({c.reason})' for c in m.candidates) or m.reason]
                for raw, m in sorted(matches.items()) if not m.found], limit)
    log.info('asu-preview: файлов %d, заявок %d, аварий %d, третья сторона %d, не выполнено %d, повторов %d',
             len(files), len(requests), sum(c.critical for _, c, _ in items), sum(c.third_party for _, c, _ in items),
             sum(r.not_done_by_resident for r, _, _ in items), len(reps))


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
