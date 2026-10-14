import logging

import pytest

from bitrix_uk.client import BitrixClient, BitrixError, ForbiddenMethodError, RateLimiter, build_query
from bitrix_uk.config import RedactFilter
from fake_portal import WEBHOOK, FakePortal


def make(portal, **kw):
    sleeps = []
    bx = BitrixClient(WEBHOOK, transport=portal.transport(), sleep=sleeps.append, requests_per_second=0, **kw)
    return bx, sleeps


def test_delete_methods_are_never_allowed():
    bx, _ = make(FakePortal(), allow_write=True)
    for m in ('crm.item.delete', 'tasks.task.delete', 'crm.timeline.comment.delete', 'user.delete'):
        with pytest.raises(ForbiddenMethodError):
            bx.call(m, {'id': 1})


def test_unknown_method_is_not_allowed():
    bx, _ = make(FakePortal(), allow_write=True)
    with pytest.raises(ForbiddenMethodError):
        bx.call('crm.item.import', {})


def test_write_requires_allow_write():
    portal = FakePortal()
    bx, _ = make(portal)
    with pytest.raises(ForbiddenMethodError, match='--apply'):
        bx.call('crm.item.add', {'entityTypeId': 1092, 'fields': {'title': 'x'}})
    assert portal.calls == []  # до портала запрос не дошёл


def test_batch_checks_inner_commands():
    bx, _ = make(FakePortal(), allow_write=True)
    with pytest.raises(ForbiddenMethodError):
        bx.batch({'a': ('crm.item.delete', {'entityTypeId': 1092, 'id': 5})})
    bx_ro, _ = make(FakePortal())
    with pytest.raises(ForbiddenMethodError):
        bx_ro.batch({'a': ('crm.item.update', {'entityTypeId': 1092, 'id': 5, 'fields': {}})})


def test_batch_limit_50():
    bx, _ = make(FakePortal(), allow_write=True)
    with pytest.raises(ValueError):
        bx.batch({str(i): ('crm.item.get', {'id': i}) for i in range(51)})


def test_retry_on_query_limit_with_exponential_pause():
    portal = FakePortal()
    portal.fail_next = [{'error': 'QUERY_LIMIT_EXCEEDED'}, {'error': 'QUERY_LIMIT_EXCEEDED'},
                        {'status': 502}]
    bx, sleeps = make(portal)
    assert 'crm' in bx.result('scope')
    assert sleeps == [1, 2, 4]


def test_gives_up_after_max_retries():
    portal = FakePortal()
    portal.fail_next = [{'error': 'QUERY_LIMIT_EXCEEDED'} for _ in range(10)]
    bx, sleeps = make(portal, max_retries=3)
    with pytest.raises(BitrixError, match='NO_RESPONSE'):
        bx.result('scope')
    assert sleeps == [1, 2, 4]


def test_error_has_hint_and_no_webhook():
    portal = FakePortal()
    portal.fail_next = [{'status': 401, 'error': 'insufficient_scope', 'error_description': 'нет прав'}]
    bx, _ = make(portal)
    with pytest.raises(BitrixError) as e:
        bx.result('scope')
    assert 'crm, task, user' in str(e.value)
    assert 'testkey' not in str(e.value)


def test_iter_list_follows_next():
    bx, _ = make(FakePortal())
    users = list(bx.iter_list('user.get', {'FILTER': {'ACTIVE': True}}))
    assert len(users) == 62


def test_rate_limiter_two_per_second():
    now = [0.0]
    slept = []

    def sleep(x):
        slept.append(round(x, 3))
        now[0] += x

    rl = RateLimiter(2, clock=lambda: now[0], sleep=sleep)
    for _ in range(4):
        rl.wait()
    assert slept == [0.5, 0.5, 0.5]
    assert now[0] == pytest.approx(1.5)


def test_build_query_php_style():
    q = build_query({'entityTypeId': 1092, 'fields': {'title': 'ул. Ленина, 1', 'ufCrm13Uk': 101},
                     'select': ['id', 'title']})
    assert q == ('entityTypeId=1092&fields[title]=%D1%83%D0%BB.%20%D0%9B%D0%B5%D0%BD%D0%B8%D0%BD%D0%B0%2C%201'
                 '&fields[ufCrm13Uk]=101&select[0]=id&select[1]=title')


def test_redact_filter_hides_webhook():
    rec = logging.LogRecord('x', logging.INFO, __file__, 1, 'адрес %s', (WEBHOOK + 'scope.json',), None)
    RedactFilter([WEBHOOK, 'testkeyabcdef123456']).filter(rec)
    assert 'testkey' not in rec.getMessage()
    rec = logging.LogRecord('x', logging.INFO, __file__, 1, 'https://ul-73.ru/rest/9/abcdefghijk/x', None, None)
    RedactFilter([]).filter(rec)
    assert 'abcdefghijk' not in rec.getMessage()
