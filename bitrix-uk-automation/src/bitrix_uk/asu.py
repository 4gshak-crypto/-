"""Чтение и разбор выгрузок журнала заявок АСУ «Жилищный стандарт» (ADocumentJournal_appealss-*.xlsx).

Что важно о формате (по выгрузке от 07.10.2026):
- сверху строки с параметрами фильтра, заголовки — в строке, где есть «№», «Время создания» и «Статус»;
- в «Комментарии» только последний комментарий: «текст» и строка «ДД.ММ.ГГГГ г., ЧЧ:ММ Сотрудник»;
- время создания в АСУ бывает смещено на час, поэтому время передачи берём из отметки комментария.

Персональные данные: колонки «Заявитель» и «Автор» не читаются вообще; телефоны, e-mail
и ФИО с инициалами в тексте заявки и комментарии маскируются.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import openpyxl
import yaml

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

# колонки, которые читаем: заголовок в АСУ → имя поля
COLUMNS = {
    '№': 'number', 'Помещение': 'room', 'Время создания': 'created_at', 'Содержание': 'content',
    'Тип': 'type', 'Дом': 'house', 'Источник': 'source', 'Реакция жильца': 'reaction',
    'Исполнитель': 'executor', 'Комментарий': 'comment', 'Адрес': 'address', 'Статус': 'status',
}
REQUIRED = ('№', 'Время создания', 'Содержание', 'Дом', 'Комментарий', 'Статус')
NOT_READ = ('Заявитель', 'Автор')  # персональные данные жителей и лишние ФИО — не читаем
HEADER_SCAN_ROWS = 30

STAMP_RE = re.compile(r'^(\d{2}\.\d{2}\.\d{4})\s*г?\.?,?\s*(\d{1,2}:\d{2})\s+(.+)$')
BASIS_RE = re.compile(r'На основании:\s*Задача\s*№\s*(\d+)', re.I)
PERIOD_RE = re.compile(r'(\d{2}\.\d{2}\.\d{4})\s+(\d{1,2}:\d{2}).*?(\d{2}\.\d{2}\.\d{4})\s+(\d{1,2}:\d{2})')
FILE_DATE_RE = re.compile(r'(\d{2})-(\d{2})-(\d{4})')

PHONE_RE = re.compile(r'(?<!\d)(?:\+7|8)?[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)'
                      r'|(?<![\d.])\d{2,3}-\d{2}-\d{2}(?![\d.])')
TEL_RE = re.compile(r'(\bтел(?:\.|ефон\w*)?\s*[:№.]?\s*)\d[\d\- ]{4,}\d', re.I)  # «по тел. 612254»
EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+')
FIO_RE = re.compile(r'\b[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.'                      # Иванов И. И.
                    r'|\b[А-ЯЁ]\.\s?[А-ЯЁ]\.\s?[А-ЯЁ][а-яё]+'                    # И. И. Иванов
                    r'|\b[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:вич|вна|чна|ична)\b')  # с отчеством


class AsuFormatError(ValueError):
    """Файл не похож на журнал заявок АСУ."""


def mask_pd(text: str | None) -> str:
    """Маскирует телефоны, e-mail и ФИО с инициалами. Названия улиц («Розы Люксембург») не трогает."""
    t = str(text or '')
    t = EMAIL_RE.sub('[e-mail]', t)
    t = PHONE_RE.sub('[телефон]', t)
    t = TEL_RE.sub(r'\1[телефон]', t)
    return FIO_RE.sub('[ФИО]', t)


def _norm(text: Any) -> str:
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def _search_text(text: str) -> str:
    return _norm(text).lower().replace('ё', 'е')


@dataclass
class CommentEntry:
    text: str                 # текст без подписи, маскированный
    at: dt.datetime | None    # отметка времени из комментария
    by: str = ''              # сотрудник УК, оставивший комментарий (в журнал программы не пишется)


@dataclass
class AsuRequest:
    number: int
    created_at: dt.datetime
    house: str
    content: str
    status: str
    room: str = ''
    type: str = ''
    source: str = ''
    reaction: str = ''        # «5», «Не выполнено» или пусто
    executor: str = ''
    comments: list[CommentEntry] = field(default_factory=list)
    basis_task: int | None = None
    file: str = ''

    @property
    def comment_text(self) -> str:
        return ' / '.join(c.text for c in self.comments if c.text)

    @property
    def not_done_by_resident(self) -> bool:
        return self.reaction.lower() == 'не выполнено'


@dataclass
class AsuJournal:
    path: Path
    requests: list[AsuRequest]
    period: tuple[dt.datetime, dt.datetime] | None = None
    warnings: list[str] = field(default_factory=list)


def parse_comment(raw: Any) -> list[CommentEntry]:
    """«текст\\nДД.ММ.ГГГГ г., ЧЧ:ММ Фамилия И. О.» → записи. Текст без отметки — запись без времени."""
    entries: list[CommentEntry] = []
    buf: list[str] = []
    for line in str(raw or '').splitlines():
        line = line.strip()
        if not line:
            continue
        m = STAMP_RE.match(line)
        if m:
            at = dt.datetime.strptime(f'{m[1]} {m[2]}', '%d.%m.%Y %H:%M')
            entries.append(CommentEntry(mask_pd(' '.join(buf)), at, m[3].strip()))
            buf = []
        else:
            buf.append(line)
    if buf:
        entries.append(CommentEntry(mask_pd(' '.join(buf)), None))
    return entries


def _to_datetime(v: Any) -> dt.datetime | None:
    if isinstance(v, dt.datetime):
        return v
    s = _norm(v)
    for fmt in ('%d.%m.%Y %H:%M:%S', '%d.%m.%Y %H:%M', '%Y-%m-%d %H:%M:%S', '%d.%m.%Y'):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _find_header(rows: list[tuple]) -> tuple[int, dict[str, int]]:
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        names = {_norm(v): j for j, v in enumerate(row) if v not in (None, '')}
        if all(c in names for c in ('№', 'Время создания', 'Статус')):
            missing = [c for c in REQUIRED if c not in names]
            if missing:
                raise AsuFormatError('в журнале нет колонок: ' + ', '.join(missing))
            return i, names
    raise AsuFormatError('не найдена строка заголовков (ожидаются «№», «Время создания», «Статус»)')


def read_journal(path: Path) -> AsuJournal:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(wb.worksheets[0].iter_rows(values_only=True))
    finally:
        wb.close()
    head, names = _find_header(rows)
    col = {COLUMNS[name]: j for name, j in names.items() if name in COLUMNS}
    journal = AsuJournal(path=path, requests=[])
    for row in rows[:head]:
        m = PERIOD_RE.search(' '.join(_norm(v) for v in row if v))
        if m:
            journal.period = (dt.datetime.strptime(f'{m[1]} {m[2]}', '%d.%m.%Y %H:%M'),
                              dt.datetime.strptime(f'{m[3]} {m[4]}', '%d.%m.%Y %H:%M'))

    def get(row: tuple, key: str) -> Any:
        j = col.get(key)
        return row[j] if j is not None and j < len(row) else None

    for n, row in enumerate(rows[head + 1:], start=head + 2):
        number = get(row, 'number')
        if number in (None, ''):
            continue
        try:
            number = int(str(number).strip())
        except ValueError:
            journal.warnings.append(f'строка {n}: номер заявки «{number}» не число — пропущена')
            continue
        created = _to_datetime(get(row, 'created_at'))
        if created is None:
            journal.warnings.append(f'строка {n}, заявка {number}: не разобрано время создания — пропущена')
            continue
        house = _norm(get(row, 'house'))
        if not house:
            # в «Адресе» есть квартира — берём только дом
            house = re.sub(r',?\s*(кв|пом)\.?\s*\d.*$', '', _norm(get(row, 'address')), flags=re.I)
        comments = parse_comment(get(row, 'comment'))
        basis = BASIS_RE.search(' '.join(c.text for c in comments))
        reaction = get(row, 'reaction')
        journal.requests.append(AsuRequest(
            number=number, created_at=created, house=house,
            content=mask_pd(_norm(get(row, 'content'))),
            status=_norm(get(row, 'status')),
            room=_norm(get(row, 'room')), type=_norm(get(row, 'type')), source=_norm(get(row, 'source')),
            reaction=_norm(reaction) if reaction is not None else '', executor=_norm(get(row, 'executor')),
            comments=comments, basis_task=int(basis[1]) if basis else None, file=path.name,
        ))
    log.info('АСУ: %s — заявок %d, предупреждений %d', path.name, len(journal.requests), len(journal.warnings))
    return journal


def file_date(path: Path) -> dt.date | None:
    m = FILE_DATE_RE.search(path.stem)
    if not m:
        return None
    try:
        return dt.date(int(m[3]), int(m[2]), int(m[1]))
    except ValueError:
        return None


def read_journals(paths: Iterable[Path]) -> tuple[list[AsuRequest], list[AsuJournal]]:
    """Читает несколько выгрузок. Одна заявка в нескольких файлах — берётся из самого свежего файла."""
    journals = [read_journal(p) for p in sorted(paths, key=lambda p: (file_date(p) or dt.date.min, p.name))]
    latest: dict[int, AsuRequest] = {}
    for j in journals:
        for r in j.requests:
            latest[r.number] = r
    return sorted(latest.values(), key=lambda r: r.created_at), journals


# --- классификация ---

@dataclass
class Rules:
    critical_types: set[str]
    critical_keywords: dict[str, tuple[re.Pattern, re.Pattern | None]]   # причина → (выражение, исключение)
    system_by_type: dict[str, str]
    system_keywords: dict[str, re.Pattern]
    third_party_status: str
    transfer: re.Pattern
    recipients: dict[str, re.Pattern]
    repeat_days: int = 30
    repeat_min: int = 3


def load_rules(path: Path | None = None) -> Rules:
    data = yaml.safe_load((path or CONFIG_DIR / 'asu_rules.yaml').read_text(encoding='utf-8'))
    rx = lambda d: {k: re.compile(v, re.I) for k, v in (d or {}).items()}  # noqa: E731

    def rx_unless(d: dict) -> dict[str, tuple[re.Pattern, re.Pattern | None]]:
        out = {}
        for k, v in (d or {}).items():
            if isinstance(v, dict):
                out[k] = (re.compile(v['pattern'], re.I), re.compile(v['unless'], re.I) if v.get('unless') else None)
            else:
                out[k] = (re.compile(v, re.I), None)
        return out

    tp = data['third_party']
    return Rules(
        critical_types=set(data['critical'].get('types') or []),
        critical_keywords=rx_unless(data['critical'].get('keywords')),
        system_by_type=dict(data['systems'].get('by_type') or {}),
        system_keywords=rx(data['systems'].get('keywords')),
        third_party_status=tp['status'], transfer=re.compile(tp['transfer'], re.I), recipients=rx(tp['recipients']),
        repeat_days=int(data.get('repeats', {}).get('days', 30)),
        repeat_min=int(data.get('repeats', {}).get('min_count', 3)),
    )


@dataclass
class Classification:
    system: str | None
    critical: bool
    critical_reasons: list[str]
    third_party: bool
    recipient: str | None          # кому передано; None — не удалось определить
    handed_at: dt.datetime          # время передачи
    handed_at_source: str           # «комментарий» или «время создания»


def classify(r: AsuRequest, rules: Rules) -> Classification:
    text = _search_text(r.content)
    comment = _search_text(r.comment_text)

    system = rules.system_by_type.get(r.type)
    if not system:
        system = next((name for name, rx in rules.system_keywords.items() if rx.search(text)), None)

    reasons = []
    if r.type in rules.critical_types:
        reasons.append(f'тип «{r.type}»')
    reasons += [name for name, (rx, unless) in rules.critical_keywords.items()
                if rx.search(text) and not (unless and unless.search(text))]

    third = _norm(r.status).lower() == rules.third_party_status.lower()
    recipient = None
    if third:
        for source in (comment, _search_text(r.type), text):
            recipient = next((name for name, rx in rules.recipients.items() if rx.search(source)), None)
            if recipient:
                break

    # время передачи: для третьей стороны — запись «передано…», иначе первая запись с отметкой времени
    stamped = [c for c in r.comments if c.at]
    handed = None
    if third:
        handed = next((c.at for c in stamped if rules.transfer.search(_search_text(c.text))), None)
    if handed is None and stamped:
        handed = min(c.at for c in stamped)
    return Classification(system=system, critical=bool(reasons), critical_reasons=reasons, third_party=third,
                          recipient=recipient, handed_at=handed or r.created_at,
                          handed_at_source='комментарий' if handed else 'время создания')


@dataclass
class Repeat:
    house: str
    system: str
    numbers: list[int]
    first: dt.datetime
    last: dt.datetime


def find_repeats(items: Iterable[tuple[AsuRequest, Classification, str]], rules: Rules) -> list[Repeat]:
    """Повторяющиеся проблемы: не меньше repeat_min заявок по одной системе одного дома за repeat_days дней.
    items: (заявка, классификация, ключ дома — ID из реестра или нормализованный адрес)."""
    groups: dict[tuple[str, str], list[AsuRequest]] = defaultdict(list)
    for r, c, house_key in items:
        if c.system and c.system != 'Прочее':
            groups[(house_key, c.system)].append(r)
    out = []
    window = dt.timedelta(days=rules.repeat_days)
    for (house_key, system), reqs in groups.items():
        reqs.sort(key=lambda r: r.created_at)
        best: list[AsuRequest] = []
        start = 0
        for end in range(len(reqs)):
            while reqs[end].created_at - reqs[start].created_at > window:
                start += 1
            if end - start + 1 > len(best):
                best = reqs[start:end + 1]
        if len(best) >= rules.repeat_min:
            out.append(Repeat(best[0].house, system, [r.number for r in best], best[0].created_at, best[-1].created_at))
    return sorted(out, key=lambda x: -len(x.numbers))
