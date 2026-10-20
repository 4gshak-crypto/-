from typer.testing import CliRunner

import bitrix_uk.cli as cli
import bitrix_uk.config as config
import bitrix_uk.discover as discover
from bitrix_uk.client import BitrixClient
from fake_portal import WEBHOOK, FakePortal


def test_check_and_discover_cli(tmp_path, monkeypatch):
    portal = FakePortal()
    monkeypatch.setenv('BITRIX_WEBHOOK_URL', WEBHOOK)
    logs = tmp_path / 'logs'
    real_setup = config.setup_logging
    monkeypatch.setattr(cli, 'setup_logging', lambda s: real_setup(s, logs))
    monkeypatch.setattr(cli, 'BitrixClient', lambda url, **kw: BitrixClient(
        url, transport=portal.transport(), sleep=lambda x: None, requests_per_second=0))
    monkeypatch.setattr(discover, 'CONFIG_DIR', tmp_path)
    monkeypatch.setattr(cli, 'save_discovery', lambda d: discover.save_discovery(d, tmp_path))
    r = CliRunner().invoke(cli.app, ['check'])
    assert r.exit_code == 0, r.output
    r = CliRunner().invoke(cli.app, ['discover'])
    assert r.exit_code == 0, r.output
    assert 'Аварийное состояние' in r.output and (tmp_path / 'fields_map.yaml').exists()
    text = (logs / 'app.log').read_text(encoding='utf-8')
    assert 'discover: сохранено' in text and 'testkey' not in text
    r = CliRunner().invoke(cli.app, ['import-houses'])
    assert r.exit_code == 2


def test_asu_preview_offline(tmp_path, monkeypatch):
    from asu_fixture import APPLICANT, make_journal
    monkeypatch.delenv('BITRIX_WEBHOOK_URL', raising=False)          # вебхук не нужен
    logs = tmp_path / 'logs'
    real_setup = config.setup_logging
    monkeypatch.setattr(cli, 'setup_logging', lambda s: real_setup(s, logs))
    asu_dir = tmp_path / 'asu'
    asu_dir.mkdir()
    make_journal(asu_dir / 'ADocumentJournal_appealss-07-03-2026.xlsx')
    houses = tmp_path / 'houses.csv'
    houses.write_text('﻿Название;Короткий адрес;GUID дома (ГИС)\nул. Ленина, 10;Ленина ул, 10;g-1\n',
                      encoding='utf-8')
    r = CliRunner().invoke(cli.app, ['asu-preview', str(asu_dir), '--houses', str(houses)], terminal_width=200)
    assert r.exit_code == 0, r.output
    assert 'Аварии: 3' in r.output and 'Третья сторона' in r.output and 'Водоканал' in r.output
    assert 'найдено 1' in r.output and 'не найдено 1' in r.output   # ул. Тихая, 4 нет в реестре
    assert APPLICANT not in r.output and '000-11-22' not in r.output
    log_text = (logs / 'app.log').read_text(encoding='utf-8')
    assert 'asu-preview: файлов 1, заявок 9' in log_text and 'Течь' not in log_text
