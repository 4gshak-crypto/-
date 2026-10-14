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
