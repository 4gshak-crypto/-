"""Вымышленный портал Битрикс24 для тестов (httpx.MockTransport). Данные выдуманы."""
from __future__ import annotations

import json

import httpx

WEBHOOK = 'https://ul-73.ru/rest/7/testkeyabcdef123456/'

FIELDS = {
    'id': {'type': 'integer', 'isReadOnly': True, 'title': 'ID', 'upperName': 'ID'},
    'title': {'type': 'string', 'isRequired': True, 'title': 'Название', 'upperName': 'TITLE'},
    'stageId': {'type': 'crm_status', 'title': 'Стадия', 'upperName': 'STAGE_ID'},
    'assignedById': {'type': 'user', 'title': 'Ответственный', 'upperName': 'ASSIGNED_BY_ID'},
    'ufCrm13GisGuid': {'type': 'string', 'title': 'UF_CRM_13_GIS_GUID', 'formLabel': 'GUID дома (ГИС)',
                       'upperName': 'UF_CRM_13_GIS_GUID'},
    'ufCrm13ShortAddr': {'type': 'string', 'title': 'Короткий адрес', 'upperName': 'UF_CRM_13_SHORT_ADDR'},
    'ufCrm13Area': {'type': 'double', 'title': 'Общая площадь м2', 'upperName': 'UF_CRM_13_AREA'},
    'ufCrm13Uk': {'type': 'enumeration', 'title': 'УК (юрлицо)', 'upperName': 'UF_CRM_13_UK',
                  'items': [{'ID': '101', 'VALUE': 'УК СВ'}, {'ID': '102', 'VALUE': 'УК СОЮЗ'},
                            {'ID': '103', 'VALUE': 'ДОМОВОЙ'}]},
    'ufCrm13Floors': {'type': 'integer', 'title': 'Этажность', 'upperName': 'UF_CRM_13_FLOORS'},
    'ufCrm13Floors2': {'type': 'integer', 'title': 'Этажность', 'upperName': 'UF_CRM_13_FLOORS2'},
    'ufCrm13YearBuilt': {'type': 'integer', 'title': 'Год постройкии', 'upperName': 'UF_CRM_13_YEAR'},
}
USERS = [
    {'ID': '1', 'LAST_NAME': 'Петров', 'NAME': 'Пётр', 'WORK_POSITION': 'Техник'},
    {'ID': '2', 'LAST_NAME': 'Шакиров', 'NAME': 'Тест', 'WORK_POSITION': 'Инженер'},
] + [{'ID': str(i), 'LAST_NAME': f'Сотрудник{i}', 'NAME': 'Тест'} for i in range(3, 63)]


class FakePortal:
    def __init__(self, scopes=('crm', 'task', 'user', 'department'), entity_type_id=1092):
        self.scopes = list(scopes)
        self.entity_type_id = entity_type_id
        self.calls: list[tuple[str, dict]] = []
        self.fail_next: list[dict] = []  # ответы-ошибки, которые отдать перед нормальным

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.split('/')[-1].removesuffix('.json')
        params = json.loads(request.content or b'{}')
        self.calls.append((method, params))
        if self.fail_next:
            err = self.fail_next.pop(0)
            return httpx.Response(err.pop('status', 503), json=err)
        try:
            body = self.route(method, params)
        except KeyError:
            return httpx.Response(400, json={'error': 'ERROR_METHOD_NOT_FOUND', 'error_description': method})
        return httpx.Response(200, json=body)

    def route(self, m, p):
        if m == 'scope':
            return {'result': self.scopes}
        if m == 'user.current':
            return {'result': {'ID': '7', 'NAME': 'Вебхук', 'LAST_NAME': 'Тестовый'}}
        if m == 'crm.type.get':
            return {'result': {'type': {'id': p['id'], 'entityTypeId': self.entity_type_id, 'title': 'Дома'}}}
        if m == 'crm.item.list':
            return {'result': {'items': [{'id': 1}]}, 'total': 1}
        if m == 'crm.item.fields':
            return {'result': {'fields': FIELDS}}
        if m == 'crm.category.list':
            return {'result': {'categories': [{'id': 21, 'name': 'Общая', 'isDefault': 'Y'}]}}
        if m == 'crm.status.list':
            e = p['filter']['ENTITY_ID']
            assert e == 'DYNAMIC_1092_STAGE_21'
            return {'result': [
                {'STATUS_ID': 'DT1092_21:NEW', 'NAME': 'В управлении', 'SORT': '10', 'SEMANTICS': None},
                {'STATUS_ID': 'DT1092_21:UC_ALARM', 'NAME': 'Аварийное состояние', 'SORT': '20', 'SEMANTICS': None},
                {'STATUS_ID': 'DT1092_21:SUCCESS', 'NAME': 'Вышел из управления', 'SORT': '30', 'SEMANTICS': 'S'},
            ]}
        if m == 'user.get':
            f = p.get('FILTER', {})
            users = [u for u in USERS if 'LAST_NAME' not in f or u['LAST_NAME'] == f['LAST_NAME']]
            start = p.get('start', 0)
            page = users[start:start + 50]
            body = {'result': page, 'total': len(users)}
            if start + 50 < len(users):
                body['next'] = start + 50
            return body
        raise KeyError(m)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
