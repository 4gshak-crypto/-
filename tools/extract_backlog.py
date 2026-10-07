"""Достаёт из годового плана (.xls) работы февраля–августа, выполненные без акта (жёлтая заливка),
и пишет их в tracker/backlog.json. Запуск: python3 tools/extract_backlog.py <путь к .xls>"""
import json, pathlib, re, sys
import xlrd

MONTHS = {'Январь': '01', 'Февраль': '02', 'Март': '03', 'Апрель': '04', 'Май': '05', 'Июнь': '06', 'Июль': '07', 'Август': '08'}
YEAR = '2026'
CATS = [  # первое совпадение по ключевым словам
    ('ТРЖ', r'\bТРЖ\b'), ('Приборы учёта', r'УУТЭ|ОДПУ|прибор\w* учет|расходомер|поверк|калибров'),
    ('Кровля и козырьки', r'кровл|козыр|крыш'), ('Фасад и МПШ', r'МПШ|межпанел|фасад|балкон'),
    ('Электрика', r'светил|освещ|электр|ВРУ|прожектор|домофон|кабел'),
    ('Инженерные сети', r'стоя|ГВС|ХВС|ЦО\b|канализ|КНС|розлив|трубопров|радиатор|насос|кран|вентил|задвиж|отоплен|фильтр|ИТП'),
    ('Двери, окна, входные группы', r'двер|окн|входн|рам[ыа]?\b|фрамуг|стекл'),
    ('Благоустройство', r'плитк|асфальт|крыл|отмост|дерев|лавоч|скамей|урн|площадк|забор|МАФ|столбик|полусфер|клумб|газон|песк|удобрен'),
    ('Подъезды', r'подъезд|л/к|лестн|покраск|побелк|штукатур'),
    ('Санитарное содержание', r'мусор|уборк|дезинс|дератиз'),
]


def norm_addr(a):
    a = re.sub(r'\s+', ' ', str(a)).strip()
    a = re.sub(r',(?=\S)', ', ', a)
    a = re.sub(r'(\d)([а-яё])\b', lambda m: m.group(1) + m.group(2).upper(), a)
    a = a.replace('проезд', 'пр-д').replace('50 лет ВЛКСМ', '50-летия ВЛКСМ').replace(' корпус ', ' корп. ')
    return a


def norm_uk(u):
    u = re.sub(r'^ООО\s*', '', str(u)).strip().strip('"«»').replace('"', '')
    known = {'ук св': 'УК «СВ»', 'ук союз': 'УК «Союз»', 'ук домовой': 'УК «Домовой»', 'ук домок': 'УК «Домок»'}
    return known.get(u.lower(), u)


def cat_of(work):
    for name, rx in CATS:
        if re.search(rx, work, re.I):
            return name
    return 'Прочее'


def main(path):
    b = xlrd.open_workbook(path, formatting_info=True)
    s = b.sheet_by_name('2026')
    out, sec = [], None
    for r in range(s.nrows):
        a = str(s.cell_value(r, 0)).strip()
        if a in MONTHS or a in ('Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'):
            sec = a
            continue
        if sec not in MONTHS or a.startswith('Всего') or not str(s.cell_value(r, 1)).strip():
            continue
        xf = b.xf_list[s.cell_xf_index(r, 1)]
        col = b.colour_map.get(xf.background.pattern_colour_index)
        if col != (255, 255, 0):  # только жёлтые: выполнено, акта нет
            continue
        work = re.sub(r'\s+', ' ', str(s.cell_value(r, 2))).strip()
        num = lambda v: float(v) if isinstance(v, (int, float)) and v else None
        fact = str(s.cell_value(r, 6)).strip()
        out.append({'row': r + 1, 'month': YEAR + '-' + MONTHS[sec], 'addr': norm_addr(s.cell_value(r, 1)), 'uk': norm_uk(s.cell_value(r, 0)),
                    'work': work, 'cat': cat_of(work), 'basis': re.sub(r'\s+', ' ', str(s.cell_value(r, 3))).strip(),
                    'sum': num(s.cell_value(r, 4)), 'fsum': num(s.cell_value(r, 7)),
                    'src_note': 'Раздел «' + sec + '»: выполнено, акта нет (жёлтая строка)' + ('; в файле: ' + fact if fact and not re.match(r'^\d', fact) else '')})
    dst = pathlib.Path(__file__).resolve().parent.parent / 'tracker' / 'backlog.json'
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(len(out), 'работ ->', dst)


if __name__ == '__main__':
    main(sys.argv[1])
