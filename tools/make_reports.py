"""Сводный трекер и перечень вопросов в Excel.
Читает tracker/merged.json и tracker/questions.json, пишет в reports/:
  Сводный трекер текущего ремонта <дата>.xlsx
  Вопросы для трекера <дата>.xlsx"""
import calendar, datetime, json, pathlib
from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = pathlib.Path(__file__).resolve().parent.parent
M = json.loads((ROOT / 'tracker' / 'merged.json').read_text(encoding='utf-8'))
Q = json.loads((ROOT / 'tracker' / 'questions.json').read_text(encoding='utf-8'))
DATE = datetime.date.fromisoformat(Q['generated'])
OUT = ROOT / 'reports'
OUT.mkdir(exist_ok=True)

F = 'Arial'
H_FILL = PatternFill('solid', fgColor='1F3A4D')
H_FONT = Font(name=F, bold=True, color='FFFFFF', size=10)
BASE = Font(name=F, size=10)
BOLD = Font(name=F, size=10, bold=True)
TITLE = Font(name=F, size=14, bold=True)
NOTE = Font(name=F, size=9, italic=True, color='5B665F')
INPUT = PatternFill('solid', fgColor='FFF7D6')
thin = Side(style='thin', color='D9DDD6')
GRID = Border(left=thin, right=thin, top=thin, bottom=thin)
WRAP = Alignment(wrap_text=True, vertical='top')
STATUS_COLORS = [  # статус -> заливка строки
    ('Принято, акт есть', 'E0F1E2'), ('Выполнено, акта нет', 'EEF2D6'), ('Снято', 'ECEEEC'), ('Отложено на зиму', 'DDEFF1'),
    ('Нужно решение', 'FBE5E1'), ('Требует уточнения', 'FBE5E1'), ('Нет статуса', 'FBE5E1'),
]
STATUSES = ['Нужно решение', 'Требует уточнения', 'Нет статуса', 'Вопрос капремонта', 'Голосование ОСС', 'Не начато', 'Передано исполнителю',
            'На контроле', 'Материал заказан', 'В работе', 'Отложено на зиму', 'Выполнено, акта нет', 'Принято, акт есть', 'Снято']
OPEN_EXCL = ['Выполнено, акта нет', 'Принято, акт есть', 'Снято', 'Отложено на зиму']
MN = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']


def header(ws, row, names, widths):
    for c, (n, w) in enumerate(zip(names, widths), 1):
        cell = ws.cell(row=row, column=c, value=n)
        cell.font, cell.fill, cell.alignment, cell.border = H_FONT, H_FILL, Alignment(wrap_text=True, vertical='center'), GRID
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.row_dimensions[row].height = 30


def body(cell, fmt=None, bold=False):
    cell.font = BOLD if bold else BASE
    cell.alignment, cell.border = WRAP, GRID
    if fmt:
        cell.number_format = fmt


def printable(book):
    for sh in book.worksheets:
        sh.page_setup.orientation = 'landscape'
        sh.page_setup.fitToWidth, sh.page_setup.fitToHeight = 1, 0
        sh.sheet_properties.pageSetUpPr.fitToPage = True


def month_end(m):
    y, mm = map(int, m.split('-'))
    return datetime.date(y, mm, calendar.monthrange(y, mm)[1])


# ======================= сводный трекер =======================
wb = Workbook()
sv = wb.active
sv.title = 'Сводка'
ws = wb.create_sheet('Работы')
cols = ['№', 'Месяц плана', 'Срок (конец месяца)', 'Адрес', 'Управляющая компания', 'Работа', 'Вид работ', 'Основание', 'Оценка, ₽', 'Факт, ₽', 'Исполнитель',
        'Мастер участка', 'Статус', 'Акт', 'Просрочено, дней', 'Стадия Битрикс24', 'Сроки Битрикс24', 'Сверить', 'Источники статуса',
        'Строка годового плана']
widths = [5, 11, 11, 26, 13, 44, 18, 30, 12, 12, 13, 20, 20, 18, 11, 16, 26, 40, 50, 9]
header(ws, 1, cols, widths)
items = sorted(M['items'], key=lambda i: (i['month'], i['addr'], i['row'] or 9999))
for r, i in enumerate(items, 2):
    vals = [r - 1, MN[int(i['month'][5:]) - 1] + ' ' + i['month'][:4], month_end(i['month']), i['addr'], i['uk'], i['work'], i['cat'], i['basis'],
            i['sum'], i['fsum'], i['ex'], i['master'] or '(не назначен)', i['status'], i['act'], None, i['bx_stage'], i['bx_dates'], i['check'], i['src_note'], i['row']]
    for c, v in enumerate(vals, 1):
        cell = ws.cell(row=r, column=c, value=v)
        body(cell, '#,##0' if c in (9, 10) else 'DD.MM.YYYY' if c == 3 else None)
    # просрочка считается от сегодняшней даты открытия файла
    ws.cell(row=r, column=15, value='=IF(AND(COUNTIF(Словарь!$A$2:$A$5,M%d)=0,C%d<TODAY()),TODAY()-C%d,"")' % (r, r, r)).number_format = '0'
last = len(items) + 1
ws.freeze_panes = 'E2'
ws.auto_filter.ref = 'A1:%s%d' % (get_column_letter(len(cols)), last)
for st, color in STATUS_COLORS:
    ws.conditional_formatting.add('A2:%s%d' % (get_column_letter(len(cols)), last),
                                  FormulaRule(formula=['$M2="%s"' % st], fill=PatternFill('solid', fgColor=color)))
ws.conditional_formatting.add('O2:O%d' % last, FormulaRule(formula=['AND(ISNUMBER($O2),$O2>0)'], font=Font(name=F, bold=True, color='C0392B')))

# словарь закрытых статусов (на него ссылаются формулы) и соответствие статусов источников
sl = wb.create_sheet('Словарь')
header(sl, 1, ['Закрытые статусы (не считаются просрочкой)'], [40])
for r, v in enumerate(OPEN_EXCL, 2):
    body(sl.cell(row=r, column=1, value=v))
sl.cell(row=7, column=1, value='Соответствие статусов в источниках и в трекере').font = BOLD
header(sl, 8, ['Источник', 'Как записано в источнике', 'Статус в трекере', 'Примечание'], [40, 34, 24, 50])
MAP = [
    ('Годовой план ПТО', 'зелёная строка', 'Принято, акт есть', ''),
    ('Годовой план ПТО', 'жёлтая строка, «Выполнено», «Акта нет»', 'Выполнено, акта нет', ''),
    ('Годовой план ПТО', 'красная строка, «отмена», «отказ»', 'Снято', ''),
    ('Годовой план ПТО', 'оранжевая строка', '(исполнитель УК)', 'цвет говорит об исполнителе, а не о статусе'),
    ('Годовой план ПТО', 'серая строка', '(исполнитель — Подрядчики)', 'цвет говорит об исполнителе, а не о статусе'),
    ('Файл исполнителей', 'в столбце исполнителя «ПТО»', '(исполнитель — Подрядчики)', ''),
    ('Файл исполнителей', 'в столбце исполнителя мастер или электрик', '(исполнитель УК)', 'работа своими силами'),
    ('Файл исполнителей', 'выполнено', 'Выполнено, акта нет', 'пока ПТО не подтвердит акт'),
    ('Файл исполнителей', 'в работе', 'В работе', ''),
    ('Файл исполнителей', 'на контроле', 'На контроле', 'предложение: заменить на «В работе» с комментарием, что мешает'),
    ('Файл исполнителей', 'зима', 'Отложено на зиму', ''),
    ('Файл исполнителей', 'отказ, отмена', 'Снято', ''),
    ('Файл исполнителей', '?????', 'Требует уточнения', ''),
    ('Файл исполнителей', 'Акт в ПТО / Акта нет / как подписывать', '(поле «Акт»)', 'это состояние акта, а не статус работы'),
    ('Битрикс24', 'Запланировано', 'не меняет статус', 'стоит и у выполненных работ — стадии не ведутся'),
    ('Битрикс24', 'В работе, Просрочено, В работе. Утверждена дата', 'В работе', ''),
    ('Битрикс24', 'Выполнено, документы не сданы', 'Выполнено, акта нет', ''),
    ('Битрикс24', 'Успешно', 'Принято, акт есть — если есть КС-2 или зелёная строка, иначе «Выполнено, акта нет»', 'смысл стадии нужно подтвердить'),
    ('Битрикс24', 'Отказано', 'Снято', ''),
]
for r, row in enumerate(MAP, 9):
    for c, v in enumerate(row, 1):
        body(sl.cell(row=r, column=c, value=v))
sl.cell(row=r + 2, column=1, value='Предложение по соответствию — для утверждения (вопрос о едином словаре статусов).').font = NOTE

# --- сводка формулами по листу «Работы»
W = "Работы!"
rng = lambda col: "%s$%s$2:$%s$%d" % (W, col, col, last)
sv.column_dimensions['A'].width = 34
for c in 'BCDEFGHI':
    sv.column_dimensions[c].width = 14
sv['A1'] = 'Сводный трекер текущего ремонта'
sv['A1'].font = TITLE
sv['A2'] = ('Сведено %s из трёх выгрузок: годовой план ПТО от 16.10.2026, файл исполнителей от 08.10.2026 с пополнениями от 16.10.2026, '
            'Битрикс24 от 19.10.2026. Отметки прежних снимков (23.09, 06.10) не используются. Все цифры ниже считаются формулами по листу «Работы». '
            '%% выполнения = (принято с актом + выполнено, акта нет) / (всего − снято).') % DATE.strftime('%d.%m.%Y')
sv['A2'].font, sv['A2'].alignment = NOTE, WRAP
sv.merge_cells('A2:I2')
sv.row_dimensions[2].height = 42
r = 4
sv.cell(row=r, column=1, value='Итого').font = BOLD
totals = [
    ('Работ в плане', '=COUNTA(%s)' % rng('A')),
    ('Снято с плана', '=COUNTIF(%s,"Снято")' % rng('M')),
    ('Принято с актом', '=COUNTIF(%s,"Принято, акт есть")' % rng('M')),
    ('Выполнено, акта нет', '=COUNTIF(%s,"Выполнено, акта нет")' % rng('M')),
    ('Открыто (не выполнено, не снято, не на зиму)', '=B5-B6-B7-B8-COUNTIF(%s,"Отложено на зиму")' % rng('M')),
    ('из них просрочено', '=COUNTIF(%s,">0")' % rng('O')),
    ('Требуют сверки источников', '=COUNTIF(%s,"?*")' % rng('R')),
    ('Принято с актом, % от плана без снятых', '=IF(B5-B6=0,0,B7/(B5-B6))'),
    ('Выполнено всего, % от плана без снятых', '=IF(B5-B6=0,0,(B7+B8)/(B5-B6))'),
    ('Оценка по плану, ₽', '=SUMIFS(%s,%s,"<>Снято")' % (rng('I'), rng('M'))),
    ('Факт, ₽', '=SUMIFS(%s,%s,"<>Снято")' % (rng('J'), rng('M'))),
]
for k, (label, f) in enumerate(totals, 5):
    body(sv.cell(row=k, column=1, value=label))
    body(sv.cell(row=k, column=2, value=f), '0%' if '%' in label else '#,##0', bold=True)
r = k + 2


def table(title, field_col, values, start):
    sv.cell(row=start, column=1, value=title).font = BOLD
    header(sv, start + 1, [title.split(' — ')[0], 'Всего', 'Принято с актом', 'Выполнено, акта нет', 'Открыто', 'Просрочено', 'Снято',
                           '% выполнения', '% принято с актом'], [34, 14, 14, 14, 14, 14, 14, 14, 14])
    for n, v in enumerate(values, start + 2):
        body(sv.cell(row=n, column=1, value=v))
        crit = '"%s"' % v
        f = [
            '=COUNTIF(%s,%s)' % (rng(field_col), crit),
            '=COUNTIFS(%s,%s,%s,"Принято, акт есть")' % (rng(field_col), crit, rng('M')),
            '=COUNTIFS(%s,%s,%s,"Выполнено, акта нет")' % (rng(field_col), crit, rng('M')),
            '=B{0}-C{0}-D{0}-COUNTIFS({1},{2},{3},"Снято")-COUNTIFS({1},{2},{3},"Отложено на зиму")'.format(n, rng(field_col), crit, rng('M')),
            '=COUNTIFS(%s,%s,%s,">0")' % (rng(field_col), crit, rng('O')),
            '=COUNTIFS(%s,%s,%s,"Снято")' % (rng(field_col), crit, rng('M')),
        ]
        f += ['=IF(B{0}-G{0}=0,"",(C{0}+D{0})/(B{0}-G{0}))'.format(n), '=IF(B{0}-G{0}=0,"",C{0}/(B{0}-G{0}))'.format(n)]
        for c, ff in enumerate(f, 2):
            body(sv.cell(row=n, column=c, value=ff), '0%' if c >= 8 else '#,##0', bold=(c == 8))
    return start + 2 + len(values) + 1


masters = sorted({i['master'] for i in M['items'] if i['master']}) + ['(не назначен)']
r = table('Мастер участка — ход работ', 'L', masters, r)
r = table('Исполнитель — ход работ', 'K', ['УК', 'Подрядчики', 'Не распределено'], r)
months = sorted({i['month'] for i in M['items']})
r = table('Месяц плана — ход работ', 'B', [MN[int(m[5:]) - 1] + ' ' + m[:4] for m in months], r)
r = table('Управляющая компания — ход работ', 'E', sorted({i['uk'] for i in M['items']}), r)
sv.cell(row=r, column=1, value='«Просрочено» — открытая работа, у которой закончился месяц плана; считается от сегодняшней даты.').font = NOTE

# --- лист сверки
sc = wb.create_sheet('Сверка')
header(sc, 1, ['Адрес', 'Работа', 'Месяц', 'Статус в трекере', 'Мастер', 'Что расходится', 'Решение'], [26, 44, 12, 20, 20, 60, 30])
chk = [i for i in items if i['check']]
for n, i in enumerate(chk, 2):
    for c, v in enumerate([i['addr'], i['work'], MN[int(i['month'][5:]) - 1], i['status'], i['master'], i['check'], None], 1):
        body(sc.cell(row=n, column=c, value=v))
    sc.cell(row=n, column=7).fill = INPUT
sc.freeze_panes = 'C2'
sc.auto_filter.ref = 'A1:G%d' % (len(chk) + 1)
sc.cell(row=len(chk) + 3, column=1, value='Столбец «Решение» (жёлтый) заполняет ПТО или администратор трекера, например: «верно по плану», «адрес — Пушкарева 74».').font = NOTE
wb.move_sheet('Словарь', offset=2)
name1 = OUT / ('Сводный трекер текущего ремонта %s.xlsx' % DATE.strftime('%d.%m.%Y'))
printable(wb)
wb.save(name1)

# ======================= вопросы =======================
wq = Workbook()
qs = wq.active
qs.title = 'Вопросы'
qs['A1'] = 'Вопросы, без ответа на которые трекер не показывает ход работ'
qs['A1'].font = TITLE
qs['A2'] = ('Составлено %s по сверке годового плана (16.10), файла исполнителей (08.10, пополнения 16.10) и выгрузки Битрикс24 (19.10). '
            'Ответы пишите в жёлтые столбцы: «Ответ» и «Кто ответил». Например: «Акт № 15 от 07.10.2026», «перенести на ноябрь», «снять с плана». '
            'Список работ по каждому вопросу — на листе «Перечни».') % DATE.strftime('%d.%m.%Y')
qs['A2'].font, qs['A2'].alignment = NOTE, WRAP
qs.merge_cells('A2:I2')
qs.row_dimensions[2].height = 44
header(qs, 4, ['№', 'Кому', 'Тема', 'Вопрос', 'Зачем это трекеру', 'Работ в перечне', 'Срок ответа', 'Ответ', 'Кто ответил'],
       [5, 20, 14, 70, 48, 11, 13, 40, 18])
for n, q in enumerate(Q['questions'], 5):
    vals = [q['n'], q['to'], q['topic'], q['text'], q['why'], None, q['term'], None, None]
    for c, v in enumerate(vals, 1):
        body(qs.cell(row=n, column=c, value=v), bold=(c == 1))
    # число работ считается по листу «Перечни»
    qs.cell(row=n, column=6, value='=IF(COUNTIF(Перечни!$A:$A,A%d)=0,"—",COUNTIF(Перечни!$A:$A,A%d))' % (n, n))
    for c in (8, 9):
        qs.cell(row=n, column=c).fill = INPUT
qs.freeze_panes = 'D5'
qs.auto_filter.ref = 'A4:I%d' % (4 + len(Q['questions']))

pe = wq.create_sheet('Перечни')
header(pe, 1, ['№ вопроса', 'Адрес', 'Работа', 'Месяц', 'Статус в трекере', 'Мастер', 'Исполнитель', 'Что уточнить', 'Ответ'],
       [9, 26, 44, 11, 20, 20, 13, 46, 30])
n = 2
for q in Q['questions']:
    for it in q['items']:
        for c, v in enumerate([q['n'], it['addr'], it['work'], it['month'], it['status'], it['master'], it['ex'], it['note'], None], 1):
            body(pe.cell(row=n, column=c, value=v))
        pe.cell(row=n, column=9).fill = INPUT
        n += 1
pe.freeze_panes = 'C2'
pe.auto_filter.ref = 'A1:I%d' % (n - 1)

# словарь статусов — на него ссылается вопрос о едином словаре
sd = wq.create_sheet('Словарь статусов')
header(sd, 1, ['Источник', 'Как записано в источнике', 'Статус в трекере', 'Примечание'], [22, 40, 34, 50])
for r, row in enumerate(MAP, 2):
    for c, v in enumerate(row, 1):
        body(sd.cell(row=r, column=c, value=v))
sd.cell(row=len(MAP) + 3, column=1, value='Предложение для утверждения. Если согласны — напишите «согласовано» в ответ на вопрос о словаре статусов.').font = NOTE
name2 = OUT / ('Вопросы для трекера %s.xlsx' % DATE.strftime('%d.%m.%Y'))
printable(wq)
wq.save(name2)
print(name1)
print(name2)
