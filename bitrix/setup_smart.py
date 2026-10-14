"""Создаёт в Битрикс24 смарт-процессы «Дома» и «Оборудование домов» для контроля УК
и заводит в «Дома» адреса из годового плана (tracker/data.json).

Запуск:
    export BITRIX_WEBHOOK=https://uk-sv.bitrix24.ru/rest/1/xxxxxxxxxxxxxxxx/
    python3 bitrix/setup_smart.py                  # создать смарт-процессы, поля, стадии, дома
    python3 bitrix/setup_smart.py --dry-run        # только показать, что будет сделано
    python3 bitrix/setup_smart.py --no-houses      # без загрузки домов
    python3 bitrix/setup_smart.py --equipment bitrix/equipment_template.csv   # загрузить оборудование

Повторный запуск безопасен: существующие смарт-процессы, поля, стадии и дома не дублируются,
а недостающее досоздаётся."""
import argparse, collections, csv, datetime, json, os, pathlib, re, sys, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAUSE = 0.55  # у облачного Битрикс24 лимит ~2 запроса в секунду

# Галочки смарт-процесса (Настройки CRM → Смарт-процессы → карточка процесса)
TYPE_FLAGS = {
    'isCategoriesEnabled': 'N', 'isStagesEnabled': 'Y', 'isBeginCloseDatesEnabled': 'N',
    'isClientEnabled': 'N', 'isMycompanyEnabled': 'N', 'isLinkWithProductsEnabled': 'N',
    'isDocumentsEnabled': 'Y', 'isSourceEnabled': 'N', 'isObserversEnabled': 'Y',
    'isRecyclebinEnabled': 'Y', 'isAutomationEnabled': 'Y', 'isBizProcEnabled': 'Y',
    'isSetOpenPermissions': 'Y', 'isUseInUserfieldEnabled': 'Y',
    # задачи и встречи календаря можно привязывать к дому и к оборудованию
    'linkedUserFields': {
        'TASKS_TASK|UF_CRM_TASK': 'true',
        'TASKS_TASK_TEMPLATE|UF_CRM_TASK': 'true',
        'CALENDAR_EVENT|UF_CRM_CAL_EVENT': 'true',
    },
}

HOUSE_TITLE = 'Дома'
EQUIP_TITLE = 'Оборудование домов'

# (код, подпись, тип, доп. параметры). Код становится полем UF_CRM_<id>_<код>.
HOUSE_FIELDS = [
    ('UK', 'Управляющая организация', 'enumeration', {'values': []}),  # значения берутся из плана
    ('CONTRACT_NO', 'Договор управления №', 'string', {}),
    ('CONTRACT_DATE', 'Дата договора управления', 'date', {}),
    ('BUILD_YEAR', 'Год постройки', 'integer', {}),
    ('FLOORS', 'Этажность', 'integer', {}),
    ('ENTRANCES', 'Подъездов', 'integer', {}),
    ('FLATS', 'Квартир', 'integer', {}),
    ('AREA', 'Общая площадь, м²', 'double', {}),
    ('WALLS', 'Материал стен', 'enumeration',
     {'values': ['Панель', 'Кирпич', 'Монолит', 'Блоки', 'Дерево', 'Смешанный']}),
    ('HEATING', 'Теплоснабжение', 'enumeration',
     {'values': ['Центральное, есть ИТП', 'Центральное, без ИТП', 'Крышная котельная', 'Поквартирное']}),
    ('GAS', 'Газифицирован', 'boolean', {}),
    ('COUNCIL', 'Председатель совета дома, телефон', 'string', {}),
    ('GIS_ID', 'Код дома в ГИС ЖКХ / ФИАС', 'string', {}),
    ('KR', 'Капремонт: работы и статус', 'string', {'rows': 3}),
    ('LAST_INSPECT', 'Последний сезонный осмотр', 'date', {}),
    ('NEXT_INSPECT', 'Следующий сезонный осмотр', 'date', {}),
    ('HEAT_PASSPORT', 'Паспорт готовности к ОЗП, дата', 'date', {}),
    ('ISSUES', 'Замечания по дому', 'string', {'rows': 4}),
    ('DOCS', 'Техпаспорт, акты осмотров, документы', 'file', {'multiple': True}),
]

EQUIP_KINDS = [
    'Лифт', 'ИТП / тепловой пункт', 'ОДПУ тепла', 'ОДПУ ХВС', 'ОДПУ ГВС', 'ОДПУ электроэнергии',
    'Насосная станция', 'ВРУ / электрощитовая', 'Противопожарная система (АППЗ, ДУ)',
    'Газовое оборудование (ВДГО)', 'Домофон / СКУД', 'Видеонаблюдение', 'Вентиляция', 'Прочее',
]
EQUIP_FIELDS = [
    ('KIND', 'Вид оборудования', 'enumeration', {'values': EQUIP_KINDS, 'mandatory': True}),
    ('PLACE', 'Место установки (подъезд, помещение)', 'string', {}),
    ('MAKER', 'Производитель', 'string', {}),
    ('MODEL', 'Модель / марка', 'string', {}),
    ('SERIAL', 'Заводской номер', 'string', {}),
    ('INV_NO', 'Инвентарный номер', 'string', {}),
    ('START_YEAR', 'Год ввода в эксплуатацию', 'integer', {}),
    ('LIFETIME', 'Нормативный срок службы, лет', 'integer', {}),
    ('CRITICAL', 'Жизнеобеспечение (контроль в первую очередь)', 'boolean', {}),
    ('CONTRACTOR', 'Обслуживающая организация', 'crm', {'settings': {'COMPANY': 'Y'}}),
    ('SERVICE_CONTRACT', 'Договор на обслуживание №, дата', 'string', {}),
    ('TO_PERIOD', 'Периодичность ТО', 'enumeration',
     {'values': ['Ежемесячно', 'Ежеквартально', 'Раз в полгода', 'Ежегодно']}),
    ('LAST_TO', 'Последнее ТО', 'date', {}),
    ('NEXT_TO', 'Следующее ТО', 'date', {}),
    ('LAST_CHECK', 'Последняя поверка / освидетельствование', 'date', {}),
    ('NEXT_CHECK', 'Следующая поверка / освидетельствование', 'date', {}),
    ('INSURANCE_TO', 'Страховка (ОСОПО) действует до', 'date', {}),
    ('DEFECTS', 'Неисправности и замечания', 'string', {'rows': 4}),
    ('DOCS', 'Паспорт, акты, протоколы', 'file', {'multiple': True}),
]

# Стадии: NEW, PREPARATION, CLIENT — в работе; SUCCESS, FAIL — финальные (карточка закрыта)
HOUSE_STAGES = {
    'NEW': ('Приёмка в управление', '#2FC6F6'),
    'PREPARATION': ('В управлении', '#7BD500'),
    'CLIENT': ('Расторжение договора', '#FFA900'),
    'SUCCESS': ('Вышел из управления', '#A8ADB4'),
    'FAIL': ('Не принят в управление', '#FF5752'),
}
EQUIP_STAGES = {
    'NEW': ('Исправно', '#7BD500'),
    'PREPARATION': ('Требует ремонта', '#FFA900'),
    'CLIENT': ('В ремонте / не работает', '#FF5752'),
    'SUCCESS': ('Списано', '#A8ADB4'),
    'FAIL': ('Передано вместе с домом', '#A8ADB4'),
}

# CSV оборудования: колонка → код поля (или служебное имя)
CSV_COLUMNS = collections.OrderedDict([
    ('Адрес дома', '@house'), ('Название', '@title'), ('Вид оборудования', 'KIND'),
    ('Место установки', 'PLACE'), ('Производитель', 'MAKER'), ('Модель', 'MODEL'),
    ('Заводской номер', 'SERIAL'), ('Инвентарный номер', 'INV_NO'), ('Год ввода', 'START_YEAR'),
    ('Срок службы, лет', 'LIFETIME'), ('Жизнеобеспечение (да/нет)', 'CRITICAL'),
    ('Договор на обслуживание', 'SERVICE_CONTRACT'), ('Периодичность ТО', 'TO_PERIOD'),
    ('Последнее ТО', 'LAST_TO'), ('Следующее ТО', 'NEXT_TO'),
    ('Последняя поверка', 'LAST_CHECK'), ('Следующая поверка', 'NEXT_CHECK'),
    ('Страховка до', 'INSURANCE_TO'), ('Состояние', '@stage'), ('Замечания', 'DEFECTS'),
])


class Bitrix:
    def __init__(self, webhook, dry):
        self.url = webhook.rstrip('/') + '/'
        self.dry = dry

    def call(self, method, params=None, write=False):
        if self.dry and write:
            if method != 'crm.item.add':  # карточки не печатаем по одной, итог будет в конце
                print('    [dry-run]', method, json.dumps(params, ensure_ascii=False)[:200])
            return None
        body = json.dumps(params or {}).encode()
        for attempt in range(5):
            req = urllib.request.Request(self.url + method + '.json', data=body,
                                         headers={'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.load(r)
            except urllib.error.HTTPError as e:
                try:
                    data = json.load(e)
                except ValueError:
                    raise SystemExit(f'{method}: HTTP {e.code}')
            except urllib.error.URLError as e:
                if attempt == 4:
                    raise SystemExit(f'{method}: нет связи с порталом ({e.reason})')
                time.sleep(2 ** attempt)
                continue
            time.sleep(PAUSE)
            if data.get('error') in ('QUERY_LIMIT_EXCEEDED', 'OPERATION_TIME_LIMIT'):
                time.sleep(2 + 2 * attempt)
                continue
            if 'error' in data:
                raise SystemExit(f"{method}: {data['error']} — {data.get('error_description', '')}")
            return data['result']
        raise SystemExit(f'{method}: портал не ответил после 5 попыток')

    def list_all(self, method, params, key):
        out, start = [], 0
        while True:
            res = self.call(method, dict(params, start=start))
            out += res[key] if key else res
            # у crm.item.list и crm.type.list нет next в result, смотрим на размер страницы
            if len(res[key] if key else res) < 50:
                return out
            start += 50


def camel(uf):
    """UF_CRM_5_BUILD_YEAR → ufCrm5BuildYear (имена полей в crm.item.*)."""
    head, *rest = uf.lower().split('_')
    return head + ''.join(p[:1].upper() + p[1:] for p in rest)


def ensure_type(bx, title, relations=None):
    found = bx.call('crm.type.list', {'filter': {'title': title}})['types']
    if found:
        t = found[0]
        print(f'  смарт-процесс «{title}» уже есть: entityTypeId={t["entityTypeId"]}, id={t["id"]}')
        return t
    fields = dict(TYPE_FLAGS, title=title)
    if relations:
        fields['relations'] = relations
    res = bx.call('crm.type.add', {'fields': fields}, write=True)
    if res is None:  # dry-run
        print(f'  создаю смарт-процесс «{title}»')
        return {'id': 0, 'entityTypeId': 0, 'title': title}
    t = res['type']
    print(f'  создан смарт-процесс «{title}»: entityTypeId={t["entityTypeId"]}, id={t["id"]}')
    return t


def ensure_fields(bx, t, spec):
    entity = f'CRM_{t["id"]}'
    have = set()
    if t['id']:
        have = {f['fieldName'] for f in bx.call('userfieldconfig.list', {
            'moduleId': 'crm', 'filter': {'entityId': entity}})['fields']}
    for sort, (code, label, utype, opt) in enumerate(spec, 1):
        name = f'UF_CRM_{t["id"]}_{code}'
        if name in have:
            continue
        lab = {'ru': label}
        field = {
            'entityId': entity, 'fieldName': name, 'userTypeId': utype, 'sort': sort * 100,
            'multiple': 'Y' if opt.get('multiple') else 'N',
            'mandatory': 'Y' if opt.get('mandatory') else 'N',
            'showFilter': 'Y', 'showInList': 'Y', 'isSearchable': 'Y',
            'editFormLabel': lab, 'listColumnLabel': lab, 'listFilterLabel': lab,
        }
        settings = dict(opt.get('settings', {}))
        if utype == 'string' and opt.get('rows'):
            settings['ROWS'] = opt['rows']
        if utype == 'boolean':
            settings.update(DISPLAY='CHECKBOX', DEFAULT_VALUE=0)
        if utype == 'enumeration':
            settings['DISPLAY'] = 'LIST'
            field['enum'] = [{'value': v, 'sort': (i + 1) * 10, 'def': 'N'} for i, v in enumerate(opt['values'])]
        if settings:
            field['settings'] = settings
        bx.call('userfieldconfig.add', {'moduleId': 'crm', 'field': field}, write=True)
        print(f'    + поле «{label}» ({utype})')


def ensure_stages(bx, t, stages):
    if not t['entityTypeId']:
        print('    стадии: ' + ' → '.join(n for n, _ in stages.values()))
        return
    cats = bx.call('crm.category.list', {'entityTypeId': t['entityTypeId']})['categories']
    cat = next(c for c in cats if c.get('isDefault') in ('Y', True)) if cats else None
    entity = f'DYNAMIC_{t["entityTypeId"]}_STAGE_{cat["id"]}'
    for st in bx.call('crm.status.list', {'filter': {'ENTITY_ID': entity}}):
        key = st['STATUS_ID'].split(':')[-1]
        if key in stages and (st['NAME'], st.get('COLOR')) != stages[key]:
            name, color = stages[key]
            bx.call('crm.status.update', {'id': st['ID'], 'fields': {'NAME': name, 'COLOR': color}}, write=True)
            print(f'    стадия {key} → «{name}»')


def enum_ids(bx, t, code):
    if not t['entityTypeId']:
        return {}
    f = bx.call('crm.item.fields', {'entityTypeId': t['entityTypeId']})['fields'][camel(f'UF_CRM_{t["id"]}_{code}')]
    return {i['VALUE']: int(i['ID']) for i in f.get('items', [])}


def add_enum_values(bx, t, code, values):
    """Дописывает в список недостающие значения (например, новую УК из плана)."""
    if not t['id']:
        return
    entity, name = f'CRM_{t["id"]}', f'UF_CRM_{t["id"]}_{code}'
    f = next(x for x in bx.call('userfieldconfig.list', {'moduleId': 'crm', 'filter': {'entityId': entity}})['fields']
             if x['fieldName'] == name)
    full = bx.call('userfieldconfig.get', {'moduleId': 'crm', 'id': f['id']})['field']
    have = [e['value'] for e in full.get('enum', [])]
    new = [v for v in values if v not in have]
    if not new:
        return
    enum = [{'id': e['id'], 'value': e['value'], 'sort': e['sort'], 'def': e['def']} for e in full.get('enum', [])]
    enum += [{'value': v, 'sort': (len(have) + i + 1) * 10, 'def': 'N'} for i, v in enumerate(new)]
    bx.call('userfieldconfig.update', {'moduleId': 'crm', 'id': f['id'], 'field': {'enum': enum}}, write=True)
    print(f'    + значения списка: {", ".join(new)}')


def houses_from_plan():
    data = json.loads((ROOT / 'tracker' / 'data.json').read_text())
    out = collections.OrderedDict()
    for g in data['groups']:
        uk = collections.Counter(i.get('uk') for i in g['items'] if i.get('uk')).most_common(1)
        kr = ''
        if g.get('kr'):
            kr = '; '.join(g['kr'].get('works', []))
            if g['kr'].get('status'):
                kr += f' ({g["kr"]["status"]})'
        out[g['addr']] = {'uk': uk[0][0] if uk else '', 'kr': kr}
    return out


def existing_items(bx, t):
    if not t['entityTypeId']:
        return {}
    items = bx.list_all('crm.item.list', {'entityTypeId': t['entityTypeId'], 'select': ['id', 'title'],
                                          'order': {'id': 'ASC'}}, 'items')
    return {norm(i['title']): i['id'] for i in items}


def norm(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip().lower().replace('ё', 'е')


def load_houses(bx, t):
    plan = houses_from_plan()
    print(f'  Дома из годового плана: {len(plan)}')
    add_enum_values(bx, t, 'UK', sorted({h['uk'] for h in plan.values() if h['uk']}))
    uk_ids = enum_ids(bx, t, 'UK')
    have = existing_items(bx, t)
    added = 0
    for addr, h in plan.items():
        if norm(addr) in have:
            continue
        fields = {'title': addr}
        if t['id']:
            if h['uk'] in uk_ids:
                fields[camel(f'UF_CRM_{t["id"]}_UK')] = uk_ids[h['uk']]
            if h['kr']:
                fields[camel(f'UF_CRM_{t["id"]}_KR')] = h['kr']
            fields['stageId'] = f'DT{t["entityTypeId"]}_{default_category(bx, t)}:PREPARATION'  # «В управлении»
        bx.call('crm.item.add', {'entityTypeId': t['entityTypeId'], 'fields': fields}, write=True)
        added += 1
    print(f'  добавлено домов: {added}, уже были: {len(plan) - added}')


_cats = {}


def default_category(bx, t):
    if t['entityTypeId'] not in _cats:
        cats = bx.call('crm.category.list', {'entityTypeId': t['entityTypeId']})['categories']
        _cats[t['entityTypeId']] = next(c['id'] for c in cats if c.get('isDefault') in ('Y', True))
    return _cats[t['entityTypeId']]


def parse_date(s):
    s = s.strip()
    for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d.%m.%y'):
        try:
            return datetime.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f'не понимаю дату «{s}», нужен формат ДД.ММ.ГГГГ')


def load_equipment(bx, house_t, eq_t, path):
    rows = list(csv.DictReader(open(path, encoding='utf-8-sig'), delimiter=';'))
    print(f'  строк в {path}: {len(rows)}')
    houses = existing_items(bx, house_t)
    have = existing_items(bx, eq_t)
    eq_types = {code: (utype, opt) for code, _, utype, opt in EQUIP_FIELDS}
    enums = {code: enum_ids(bx, eq_t, code) for code, (utype, _) in eq_types.items() if utype == 'enumeration'}
    stage_by_name = {norm(n): k for k, (n, _) in EQUIP_STAGES.items()}
    cat = default_category(bx, eq_t) if eq_t['entityTypeId'] else 0
    added, errors = 0, []
    for n, row in enumerate(rows, 2):
        row = {k.strip(): (v or '').strip() for k, v in row.items() if k}
        try:
            house = row.get('Адрес дома', '')
            if norm(house) not in houses and houses:
                raise ValueError(f'дом «{house}» не найден в смарт-процессе «Дома»')
            title = row.get('Название') or f"{row.get('Вид оборудования', 'Оборудование')} — {house}"
            if norm(title) in have:
                continue
            fields = {'title': title}
            if houses:
                fields[f'parentId{house_t["entityTypeId"]}'] = houses[norm(house)]
            for col, code in CSV_COLUMNS.items():
                val = row.get(col, '')
                if not val or code.startswith('@') and code != '@stage':
                    continue
                if code == '@stage':
                    key = stage_by_name.get(norm(val))
                    if not key:
                        raise ValueError(f'неизвестное состояние «{val}»')
                    fields['stageId'] = f'DT{eq_t["entityTypeId"]}_{cat}:{key}'
                    continue
                utype, _ = eq_types[code]
                if utype == 'date':
                    val = parse_date(val)
                elif utype == 'integer':
                    val = int(re.sub(r'\D', '', val))
                elif utype == 'boolean':
                    val = 'Y' if norm(val) in ('да', 'y', '1', 'есть', '+') else 'N'
                elif utype == 'enumeration' and eq_t['id']:
                    if val not in enums[code]:
                        raise ValueError(f'«{val}» нет в списке «{col}»')
                    val = enums[code][val]
                fields[camel(f'UF_CRM_{eq_t["id"]}_{code}')] = val
        except ValueError as e:
            errors.append(f'строка {n}: {e}')
            continue
        bx.call('crm.item.add', {'entityTypeId': eq_t['entityTypeId'], 'fields': fields}, write=True)
        have[norm(title)] = True
        added += 1
    print(f'  добавлено оборудования: {added}')
    for e in errors:
        print('  ! ' + e)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--webhook', default=os.environ.get('BITRIX_WEBHOOK', ''),
                    help='адрес входящего вебхука, можно задать переменной BITRIX_WEBHOOK')
    ap.add_argument('--dry-run', action='store_true', help='ничего не создавать, только показать план')
    ap.add_argument('--no-houses', action='store_true', help='не загружать дома из годового плана')
    ap.add_argument('--equipment', metavar='CSV', help='загрузить оборудование из CSV (разделитель «;»)')
    a = ap.parse_args()
    if not a.webhook:
        if not a.dry_run:
            sys.exit('Укажите вебхук: --webhook https://портал.bitrix24.ru/rest/1/ключ/ или BITRIX_WEBHOOK')
        a.webhook = 'https://example.bitrix24.ru/rest/1/demo/'
    bx = Bitrix(a.webhook, a.dry_run)
    offline = a.dry_run and 'example.bitrix24' in a.webhook
    if offline:  # без портала: показываем план целиком
        bx.call = lambda m, p=None, write=False: None if write else _offline(m)

    print('1. Смарт-процесс «Дома»')
    house = ensure_type(bx, HOUSE_TITLE)
    ensure_fields(bx, house, HOUSE_FIELDS)
    ensure_stages(bx, house, HOUSE_STAGES)

    print('2. Смарт-процесс «Оборудование домов» (привязан к дому)')
    rel = {'parent': [{'entityTypeId': house['entityTypeId'], 'isChildrenListEnabled': 'Y'}]}
    equip = ensure_type(bx, EQUIP_TITLE, rel)
    ensure_fields(bx, equip, EQUIP_FIELDS)
    ensure_stages(bx, equip, EQUIP_STAGES)

    if not a.no_houses:
        print('3. Дома')
        load_houses(bx, house)
    if a.equipment:
        print('4. Оборудование')
        load_equipment(bx, house, equip, a.equipment)
    print('Готово.' if not a.dry_run else 'Готово (dry-run, в портале ничего не менялось).')


def _offline(method):
    return {'crm.type.list': {'types': []}, 'crm.item.list': {'items': []}}.get(method)


if __name__ == '__main__':
    main()
