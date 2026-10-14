"""Команды check и discover: проверка подключения и чтение реальной схемы смарт-процесса «Дома»."""
from __future__ import annotations

import datetime as dt
import difflib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .client import BitrixClient, BitrixError
from .config import CONFIG_DIR, Settings

log = logging.getLogger(__name__)

# Колонки дома_для_импорта.csv в порядке файла
CSV_COLUMNS = [
    'Название', 'Короткий адрес', 'Адрес ОЖФ', 'Код адреса в ГИС ЖКХ', 'ФИАС GUID', 'GUID дома (ГИС)',
    'Код ОКТМО', 'Кадастровый номер', 'УК (юрлицо)', 'Наименование УО (ГИС)', 'ОГРН УО', 'Способ управления',
    'Техник/мастер участка', 'Тип дома', 'Состояние дома', 'Общая площадь, м²', 'Жилая площадь, м²',
    'Количество помещений (ГИС)', 'из них нежилых (ГИС)', 'Квартир в АСУ', 'Площадь по АСУ, м²',
    'Найден в АСУ', 'Этажность', 'Подъездов', 'Год постройки', 'Конструктив', 'Кровля: тип', 'Отопление',
    'ГВС', 'Лифтов, шт.', 'ОДПУ тепла', 'ОДПУ воды', 'ОДПУ э/э', 'АПС', 'Программа ФКР', 'Стадия',
    'Требует проверки',
]
# Колонки, которым соответствует системное поле, а не UF
SYSTEM_COLUMNS = {'Название': 'title', 'Стадия': 'stageId'}
FUZZY_THRESHOLD = 0.85


def norm_title(s: str) -> str:
    s = str(s or '').lower().replace('ё', 'е').replace('м²', 'м2')
    s = re.sub(r'[^\w/]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def field_label(f: dict[str, Any]) -> str:
    """Подпись поля: у UF-полей подпись формы точнее, чем title (там бывает код поля)."""
    for key in ('formLabel', 'listLabel', 'filterLabel', 'title'):
        v = f.get(key)
        if v and not str(v).startswith('UF_CRM_'):
            return str(v)
    return str(f.get('title') or '')


# --- check ---

@dataclass
class CheckResult:
    ok: bool = True
    lines: list[tuple[str, str, str]] = field(default_factory=list)  # (проверка, итог, подробности)

    def add(self, name: str, ok: bool, details: str = '') -> None:
        self.lines.append((name, 'да' if ok else 'НЕТ', details))
        self.ok = self.ok and ok


def run_check(bx: BitrixClient, s: Settings) -> CheckResult:
    res = CheckResult()
    try:
        scopes = set(bx.result('scope'))
    except BitrixError as e:
        res.add('Вебхук отвечает', False, str(e))
        return res
    res.add('Вебхук отвечает', True, s.portal.domain)
    missing = [x for x in s.required_scopes if x not in scopes]
    res.add('Права вебхука: ' + ', '.join(s.required_scopes), not missing,
            ('нет прав: ' + ', '.join(missing)) if missing else 'все есть')
    try:
        me = bx.result('user.current')
        res.add('Пользователь вебхука', True, f'ID {me.get("ID")}, {me.get("LAST_NAME", "")} {me.get("NAME", "")}'.strip())
    except BitrixError as e:
        res.add('Пользователь вебхука', False, str(e))
    try:
        t = bx.result('crm.type.get', {'id': s.portal.type_id})['type']
        same = int(t['entityTypeId']) == s.portal.entity_type_id
        res.add(f'Смарт-процесс ID типа {s.portal.type_id}', same,
                f'«{t.get("title")}», entityTypeId {t.get("entityTypeId")}'
                + ('' if same else f' — в настройках указан {s.portal.entity_type_id}'))
    except BitrixError as e:
        res.add(f'Смарт-процесс ID типа {s.portal.type_id}', False, str(e))
        return res
    try:
        r = bx.call('crm.item.list', {'entityTypeId': s.portal.entity_type_id, 'select': ['id']})
        res.add('Чтение элементов «Домов»', True, f'элементов: {r.total if r.total is not None else len(r.result["items"])}')
    except BitrixError as e:
        res.add('Чтение элементов «Домов»', False, str(e))
    last = s.tasks.third_party_responsible_last_name
    if last and 'user' in scopes:
        try:
            found = bx.result('user.get', {'FILTER': {'LAST_NAME': last, 'ACTIVE': True}})
            res.add(f'Ответственный за задачи третьим сторонам ({last})', len(found) == 1,
                    'найден: ID ' + str(found[0]['ID']) if len(found) == 1
                    else f'найдено сотрудников: {len(found)} — уточните, кого назначать')
        except BitrixError as e:
            res.add(f'Ответственный ({last})', False, str(e))
    return res


# --- discover ---

def propose_mapping(fields: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Предлагает «колонка CSV → поле» только по совпадению подписей. Решение — за человеком."""
    by_label: dict[str, list[str]] = {}
    for code, f in fields.items():
        by_label.setdefault(norm_title(field_label(f)), []).append(code)
    out = []
    for col in CSV_COLUMNS:
        row: dict[str, Any] = {'column': col, 'field': None, 'field_title': None, 'match': 'нет', 'note': ''}
        if col in SYSTEM_COLUMNS and SYSTEM_COLUMNS[col] in fields:
            code = SYSTEM_COLUMNS[col]
            row.update(field=code, field_title=field_label(fields[code]), match='системное')
            out.append(row)
            continue
        key = norm_title(col)
        exact = by_label.get(key, [])
        if len(exact) == 1:
            code = exact[0]
            row.update(field=code, field_title=field_label(fields[code]), match='точно')
        elif len(exact) > 1:
            row['note'] = 'несколько полей с такой подписью: ' + ', '.join(exact)
        else:
            close = difflib.get_close_matches(key, list(by_label), n=3, cutoff=FUZZY_THRESHOLD)
            cands = [c for lbl in close for c in by_label[lbl]]
            if len(cands) == 1:
                code = cands[0]
                row.update(field=code, field_title=field_label(fields[code]), match='похоже',
                           note='подпись отличается — проверьте')
            elif cands:
                row['note'] = 'кандидаты: ' + ', '.join(f'{c} «{field_label(fields[c])}»' for c in cands)
        if col == 'Техник/мастер участка' and not row['field']:
            row['note'] = (row['note'] + '; ' if row['note'] else '') + \
                'поля с такой подписью нет; если техник — это «Ответственный», укажите assignedById'
        if row['field'] and fields[row['field']].get('isReadOnly'):
            row['note'] = (row['note'] + '; ' if row['note'] else '') + 'поле только для чтения'
        out.append(row)
    return out


def run_discover(bx: BitrixClient, s: Settings) -> dict[str, Any]:
    etid = s.portal.entity_type_id
    t = bx.result('crm.type.get', {'id': s.portal.type_id})['type']
    if int(t['entityTypeId']) != etid:
        raise BitrixError('crm.type.get', 'MISMATCH',
                          f'ID типа {s.portal.type_id} — это entityTypeId {t["entityTypeId"]}, а не {etid}')
    raw = bx.result('crm.item.fields', {'entityTypeId': etid})['fields']
    fields: dict[str, dict[str, Any]] = {}
    for code, f in raw.items():
        item = {
            'title': field_label(f),
            'uf': f.get('upperName') or code,
            'type': f.get('type'),
            'multiple': bool(f.get('isMultiple')),
            'required': bool(f.get('isRequired')),
            'readonly': bool(f.get('isReadOnly')),
        }
        if f.get('items'):
            item['items'] = [{'id': int(i['ID']), 'value': i['VALUE']} for i in f['items']]
        fields[code] = item
    stages = []
    for cat in bx.result('crm.category.list', {'entityTypeId': etid})['categories']:
        entity = f'DYNAMIC_{etid}_STAGE_{cat["id"]}'
        for st in sorted(bx.result('crm.status.list', {'filter': {'ENTITY_ID': entity}}),
                         key=lambda x: int(x.get('SORT') or 0)):
            stages.append({'category_id': int(cat['id']), 'category': cat.get('name'),
                           'status_id': st['STATUS_ID'], 'name': st['NAME'],
                           'semantics': {'S': 'успех', 'F': 'провал'}.get(st.get('SEMANTICS') or '', 'в работе')})
    users = [{'id': int(u['ID']), 'last_name': (u.get('LAST_NAME') or '').strip(),
              'name': (u.get('NAME') or '').strip(), 'second_name': (u.get('SECOND_NAME') or '').strip(),
              'position': (u.get('WORK_POSITION') or '').strip()}
             for u in bx.iter_list('user.get', {'FILTER': {'ACTIVE': True}, 'sort': 'LAST_NAME'})]
    mapping = propose_mapping(raw)
    for row in mapping:
        if row['field']:
            row['uf'] = fields[row['field']]['uf']
    return {
        'portal': s.portal.domain, 'entity_type_id': etid, 'type_id': s.portal.type_id,
        'type_title': t.get('title'), 'discovered_at': dt.datetime.now().isoformat(timespec='seconds'),
        'confirmed': False,
        'mapping': mapping, 'fields': fields, 'stages': stages, 'users_count': len(users), '_users': users,
    }


def save_discovery(data: dict[str, Any], config_dir: Path = CONFIG_DIR) -> tuple[Path, Path]:
    """Пишет config/fields_map.yaml (или .discovered.yaml, если сопоставление уже подтверждено)
    и список сотрудников в config/users.yaml (файл не попадает в git)."""
    data = dict(data)
    users = data.pop('_users')
    target = config_dir / 'fields_map.yaml'
    if target.exists():
        old = yaml.safe_load(target.read_text(encoding='utf-8')) or {}
        if old.get('confirmed'):
            target = config_dir / 'fields_map.discovered.yaml'  # подтверждённое не перезаписываем
    header = ('# Создано командой discover. Проверьте раздел mapping: поле field для каждой колонки CSV.\n'
              '# Исправьте ошибки, впишите недостающее (код поля из раздела fields), затем поставьте\n'
              '# confirmed: true. Без этого import-houses не запустится.\n')
    target.write_text(header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
                      encoding='utf-8')
    users_path = config_dir / 'users.yaml'
    users_path.write_text('# Сотрудники портала (для сопоставления техников). Не публиковать.\n'
                          + yaml.safe_dump(users, allow_unicode=True, sort_keys=False), encoding='utf-8')
    log.info('discover: сохранено %s, полей %d, стадий %d, сотрудников %d', target.name,
             len(data['fields']), len(data['stages']), len(users))
    return target, users_path
