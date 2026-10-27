"""Читает перечень работ по капитальному ремонту (.xls) и приводит его к позициям: адрес -> работы -> суммы, подрядчик, сроки, процент выполнения.

Колонки ищутся по заголовкам в строке с «Адрес» в первой колонке: решение собственников (что делаем), сумма КР, аванс из банка,
основной подрядчик, сумма по разделам, исполнитель (план), аванс/расчёт, график начала, срок окончания, сумма договора,
процент выполнения (в прежней версии файла вместо него была «фактическая сумма»).
Позиция начинается со строки, где заполнен адрес; строки без адреса — отдельные работы той же позиции."""
import calendar, datetime, re, sys, pathlib
import xlrd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from srcnorm import addr_key

sp = lambda v: re.sub(r'\s+', ' ', str(v if v is not None else '')).strip()
HEAD = [  # ключ, фрагмент заголовка
    ('work', 'решение'), ('kr', 'сумма кр'), ('bank', 'аванс из банка'), ('contractor', 'основной подрядчик'), ('sec', 'сумма по разделам'),
    ('executor', 'исполнитель'), ('pay', 'аванс/'), ('start', 'график начала'), ('end', 'срок окончания'), ('contract', 'сумма договора'),
    ('pct', 'процент'), ('fact', 'фактическая')]


def num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) or None
    return None


def text_sum(v):
    """Сумма, записанная текстом: «450т.р+438т.р» -> 888000. Остальной текст суммой не считается."""
    s = sp(v).lower().replace(' ', '')
    if not re.fullmatch(r'(\d+(?:[.,]\d+)?)т\.?р\.?(?:\+(\d+(?:[.,]\d+)?)т\.?р\.?)*', s):
        return None
    return sum(float(x.replace(',', '.')) for x in re.findall(r'(\d+(?:[.,]\d+)?)т\.?р', s)) * 1000


def parse_term(v, datemode, is_date_cell, edge='end'):
    """Срок -> (дата, подпись). «4кв 2026» — конец квартала (для начала работ — его начало); «2027» — конец года; числа и даты Excel — как есть."""
    if is_date_cell or (isinstance(v, float) and 40000 < v < 60000):
        d = xlrd.xldate_as_datetime(v, datemode).date()
        return d, d.strftime('%d.%m.%Y')
    if isinstance(v, float) and 2000 <= v <= 2100 and v == int(v):
        y = int(v)
        return (datetime.date(y, 1, 1) if edge == 'start' else datetime.date(y, 12, 31)), '%d г.' % y
    s = sp(v)
    if not s:
        return None, ''
    m = re.fullmatch(r'(\d{2})\.(\d{2})\.(\d{4})', s)
    if m:
        return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1))), s
    m = re.fullmatch(r'(\d)\s*кв\.?\s*(\d{4})', s, re.I)
    if m:
        q, y = int(m.group(1)), int(m.group(2))
        mm = q * 3
        d = datetime.date(y, mm - 2, 1) if edge == 'start' else datetime.date(y, mm, calendar.monthrange(y, mm)[1])
        return d, '%d кв. %d' % (q, y)
    return None, s


def read(path):
    b = xlrd.open_workbook(path, formatting_info=True)
    s = b.sheet_by_index(0)
    fill = lambda r, c: (lambda col: '%02X%02X%02X' % col if col else None)(b.colour_map.get(b.xf_list[s.cell_xf_index(r, c)].background.pattern_colour_index))
    isdate = lambda r, c: s.cell_type(r, c) == xlrd.XL_CELL_DATE
    hr = next((r for r in range(s.nrows) if sp(s.cell_value(r, 0)).lower() == 'адрес'), None)
    if hr is None:
        raise SystemExit('В файле нет строки заголовков с «Адрес» в первой колонке.')
    col = {'addr': 0}
    for c in range(s.ncols):
        h = sp(s.cell_value(hr, c)).lower()
        for key, frag in HEAD:
            if frag in h and key not in col:
                col[key] = c
    need = ('work', 'kr', 'contractor', 'executor', 'start', 'end')
    if any(k not in col for k in need):
        raise SystemExit('Не найдены колонки: %s' % ', '.join(k for k in need if k not in col))
    val = lambda r, k: s.cell_value(r, col[k]) if k in col else ''
    pos, cur, total = [], None, None
    for r in range(hr + 1, s.nrows):
        if not any(sp(s.cell_value(r, c)) for c in range(s.ncols)):
            continue
        addr = sp(val(r, 'addr'))
        if not addr and not sp(val(r, 'work')) and num(val(r, 'kr')) and r == s.nrows - 1:
            total = dict(kr=num(val(r, 'kr')), bank=num(val(r, 'bank')))   # итоговая строка внизу
            continue
        if addr:
            cur = dict(row=r + 1, addr=addr, kr=None, bank=None, contractor='', executor='', pay=None, contract=None, fact=None, pct=None, state='',
                       start=None, start_txt='', end=None, end_txt='', lines=[], notes=[], vote=False,
                       fills=[fill(r, col[k]) for k in ('addr', 'work', 'kr', 'bank', 'start', 'end') if k in col])
            pos.append(cur)
        if cur is None:
            continue
        for key in ('kr', 'bank', 'pay', 'contract', 'fact'):          # суммы позиции: kr, bank, pay — из первой строки; договор и факт копятся по строкам
            if key in col:
                v = num(val(r, key))
                if v is not None:
                    cur[key] = (cur[key] or 0) + v if key in ('contract', 'fact') else (cur[key] if cur[key] is not None else v)
        if 'pct' in col and cur['pct'] is None and not cur['state']:
            v = val(r, 'pct')
            if num(v) is not None:
                cur['pct'] = num(v)
            elif sp(v):
                cur['state'] = sp(v)                                    # «встали» и т. п.
        for key in ('contractor', 'executor'):
            t = sp(val(r, key))
            if t and not cur[key]:
                cur[key] = t
        for key in ('start', 'end'):
            if cur[key] is None and not cur[key + '_txt']:
                d, t = parse_term(val(r, key), b.datemode, isdate(r, col[key]), key)
                cur[key], cur[key + '_txt'] = d, t
        work, sec = sp(val(r, 'work')), num(val(r, 'sec'))
        sec_txt = sp(val(r, 'sec')) if sec is None else ''
        if sec is None and sec_txt:
            sec = text_sum(sec_txt)
            if sec is not None:
                cur['notes'].append('сумма по разделу записана текстом: «%s»' % sec_txt)
                sec_txt = ''
        cancelled = sp(val(r, 'contractor')).lower() == 'отмена'
        if work or sec or sec_txt:
            cur['lines'].append(dict(row=r + 1, work=work or '(без названия)', sum=sec, sum_txt=sec_txt, contract=num(val(r, 'contract')), cancelled=cancelled and bool(work)))
        if cancelled and not work:
            cur['notes'].append('в колонке «Основной подрядчик» стоит «отмена»')
    for p in pos:
        txt = ' '.join([p['executor'], p['contractor'], p['state']] + [l['work'] + ' ' + l['sum_txt'] for l in p['lines']]).lower()
        p['vote'] = 'переголос' in txt
        if 'переголос' in p['executor'].lower():
            p['executor'] = ''
        for l in p['lines']:
            if 'переголос' in l['sum_txt'].lower():
                l['sum_txt'] = ''
    if total is None:
        last = [s.cell_value(s.nrows - 1, c) for c in range(s.ncols)]
        if not sp(last[0]) and num(last[col['kr']]):
            total = dict(kr=num(last[col['kr']]), bank=num(last[col['bank']]) if 'bank' in col else None)
    return pos, total, col


if __name__ == '__main__':
    pos, total, col = read(sys.argv[1])
    print(len(pos), 'позиций, домов', len({addr_key(p['addr']) for p in pos}), '| колонки:', {k: v for k, v in col.items()})
    print('итог в файле:', total, '| сумма КР по позициям:', round(sum(p['kr'] or 0 for p in pos), 2), '| аванс из банка:', sum(p['bank'] or 0 for p in pos))
    for p in pos:
        print(p['row'], p['addr'][:24].ljust(24), '| КР', p['kr'], '| банк', p['bank'], '|', p['contractor'], '/', p['executor'], '| %', p['pct'], p['state'], '| старт', p['start_txt'], '| конец', p['end_txt'],
              '| договор', p['contract'], '| строк', len(p['lines']), p['notes'] or '', 'ПЕРЕГОЛОСОВАНИЕ' if p['vote'] else '')
