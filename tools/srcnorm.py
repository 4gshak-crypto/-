"""Нормализация адресов и текстов работ для сопоставления файлов плана, исполнителей и Битрикс24."""
import re, difflib

STREET_TYPES = r'(улица|проспект|пр-кт|пр-т|пр-д|проезд|шоссе|переулок|бульвар|б-р|площадь|ул|пр|ш|пер|пл|д)'
HOUSE = r'(\d+(?:\s*[а-я](?![а-я]))?(?:\s*/\s*\d+(?:\s*[а-я](?![а-я]))?)?)'


def addr_key(a):
    """('минаева', '15') из «улица Минаева, 15», «Минаева ул,15», «Нариманова пр-т. 91», «50 лет ВЛКСМ д.24»."""
    s = str(a or '').lower().replace('ё', 'е').replace('\xa0', ' ').strip()
    s = re.sub(r'50\s*-?\s*(летия|лет)', '50 лет', s)
    s = re.sub(r'\bтретьего\b', '3', s).replace('уица ', 'улица ')
    s = s.replace('промышленая', 'промышленная').replace('пушкаревау', 'пушкарева').replace('роьеспьера', 'робеспьера').replace('люксембур ', 'люксембург ')
    if ',' in s:
        street, rest = s.split(',', 1)
        m = re.search(HOUSE + r'(?:\s*(?:корпус|корп\.?|к\.?)\s*(\d+))?', rest)
    else:
        m = re.search(HOUSE + r'(?:\s*(?:корпус|корп\.?|к\.?)\s*(\d+))?\s*$', s)
        street = s[:m.start()] if m else s
    if not m:
        return (s, '')
    house, korp = re.sub(r'\s', '', m.group(1)), m.group(2)
    street = re.sub(r'(?<![а-я])' + STREET_TYPES + r'(?![а-я])\.?', ' ', street)
    street = re.sub(r'(?<![а-я])(л|у)(?![а-я])', ' ', street)  # опечатки «Минаева л», «Пушкарева у л»
    street = re.sub(r'[^а-я0-9 ]', ' ', street)
    street = ' '.join(w for w in street.split() if w != 'го')
    if korp:
        house += 'к' + korp
    return (street.strip(), house)


def work_norm(w):
    s = str(w or '').lower().replace('ё', 'е')
    s = re.sub(r'\(?\s*8\s*\d{3}[\s\d-]{6,}\)?', ' ', s)  # телефоны в тексте работы
    s = re.sub(r'[^а-я0-9№ ]', ' ', s)
    for a, b in (('сиситем', 'систем'), ('ситем', 'систем'), ('уплортнит', 'уплотнит'), ('библеотек', 'библиотек'), ('ковли', 'кровли'),
                 ('заамен', 'замен'), ('ремонтсист', 'ремонт сист'), ('ремонткровл', 'ремонт кровл'), ('кварна', 'крана'), ('прочитск', 'прочистк')):
        s = s.replace(a, b)
    return ' '.join(s.split())


def work_sim(a, b):
    a, b = work_norm(a), work_norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    r = difflib.SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    j = len(ta & tb) / max(1, len(ta | tb))
    # номера квартир/подъездов должны совпадать, иначе это разные работы
    na, nb = set(re.findall(r'\d+', a)), set(re.findall(r'\d+', b))
    if na and nb and not (na & nb):
        return min(r, j) * 0.5
    return max(r, j)
