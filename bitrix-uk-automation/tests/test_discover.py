import pytest
import yaml

from bitrix_uk.client import BitrixClient
from bitrix_uk.config import ConfigError, Settings, validate_webhook
from bitrix_uk.discover import run_check, run_discover, save_discovery
from fake_portal import WEBHOOK, FakePortal

SETTINGS = {'portal': {'domain': 'ul-73.ru', 'entity_type_id': 1092, 'type_id': 13},
            'tasks': {'third_party_responsible_last_name': 'Шакиров'}}


def client(portal):
    return BitrixClient(WEBHOOK, transport=portal.transport(), sleep=lambda x: None, requests_per_second=0)


def test_check_ok():
    res = run_check(client(FakePortal()), Settings(**SETTINGS))
    assert res.ok, res.lines
    assert any('Шакиров' in n and 'ID 2' in d for n, _, d in res.lines)


def test_check_reports_missing_scope_and_wrong_type():
    res = run_check(client(FakePortal(scopes=['crm'], entity_type_id=1036)), Settings(**SETTINGS))
    assert not res.ok
    text = str(res.lines)
    assert 'нет прав: task, user' in text and 'в настройках указан 1092' in text


def test_discover_mapping_is_only_by_labels():
    data = run_discover(client(FakePortal()), Settings(**SETTINGS))
    m = {r['column']: r for r in data['mapping']}
    assert m['Название']['field'] == 'title' and m['Стадия']['field'] == 'stageId'
    assert m['GUID дома (ГИС)']['field'] == 'ufCrm13GisGuid'          # подпись формы, а не код
    assert m['GUID дома (ГИС)']['uf'] == 'UF_CRM_13_GIS_GUID'
    assert m['Общая площадь, м²']['match'] == 'точно'                  # м² = м2, запятая не важна
    assert m['Год постройки']['match'] == 'похоже'                    # опечатка в подписи — на проверку
    assert m['Этажность']['field'] is None and 'несколько' in m['Этажность']['note']
    assert m['Техник/мастер участка']['field'] is None                # assignedById не подставляем сами
    assert m['ОГРН УО']['match'] == 'нет'
    assert data['stages'][1]['name'] == 'Аварийное состояние'
    assert data['users_count'] == 62 and data['confirmed'] is False


def test_save_discovery_keeps_confirmed_map(tmp_path):
    data = run_discover(client(FakePortal()), Settings(**SETTINGS))
    p, users = save_discovery(data, tmp_path)
    assert p.name == 'fields_map.yaml' and users.exists()
    saved = yaml.safe_load(p.read_text(encoding='utf-8'))
    assert '_users' not in saved and saved['fields']['ufCrm13Uk']['items'][0] == {'id': 101, 'value': 'УК СВ'}
    saved['confirmed'] = True
    p.write_text(yaml.safe_dump(saved, allow_unicode=True), encoding='utf-8')
    p2, _ = save_discovery(run_discover(client(FakePortal()), Settings(**SETTINGS)), tmp_path)
    assert p2.name == 'fields_map.discovered.yaml'
    assert yaml.safe_load(p.read_text(encoding='utf-8'))['confirmed'] is True


@pytest.mark.parametrize('url,err', [
    (None, 'не задан'),
    ('http://ul-73.ru/rest/1/abc/', 'неверный вид'),
    ('https://other.bitrix24.ru/rest/1/abcdef/', 'other.bitrix24.ru'),
])
def test_validate_webhook(url, err):
    s = Settings(**SETTINGS, webhook_url=url)
    with pytest.raises(ConfigError, match=err):
        validate_webhook(s)
    assert validate_webhook(Settings(**SETTINGS, webhook_url=WEBHOOK)) == WEBHOOK
