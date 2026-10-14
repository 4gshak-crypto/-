"""REST-клиент Битрикс24 через входящий вебхук.

Правила безопасности, которые обеспечивает клиент:
- вызываются только методы из белого списка; методов удаления в нём нет;
- методы записи доступны, только если клиент создан с allow_write=True
  (CLI делает так лишь после --apply и подтверждения «да»);
- не больше 2 запросов в секунду, повтор при QUERY_LIMIT_EXCEEDED и сбоях связи
  с паузами 1, 2, 4, 8, 16 с;
- адрес вебхука не попадает в журнал и в тексты ошибок.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

READ_METHODS = frozenset({
    'scope', 'user.current', 'user.get', 'profile',
    'crm.type.get', 'crm.type.list', 'crm.item.fields', 'crm.item.list', 'crm.item.get',
    'crm.category.list', 'crm.status.list', 'crm.timeline.comment.list', 'crm.activity.list',
    'tasks.task.list', 'tasks.task.get',
})
WRITE_METHODS = frozenset({
    'crm.item.add', 'crm.item.update', 'crm.timeline.comment.add', 'crm.activity.todo.add',
    'tasks.task.add',
})
RETRY_ERRORS = frozenset({'QUERY_LIMIT_EXCEEDED', 'OPERATION_TIME_LIMIT', 'INTERNAL_SERVER_ERROR'})
BATCH_LIMIT = 50

ERROR_HINTS = {
    'insufficient_scope': 'у вебхука нет нужных прав — добавьте права crm, task, user в настройках вебхука',
    'INVALID_CREDENTIALS': 'вебхук не принят порталом — проверьте адрес или создайте вебхук заново',
    'expired_token': 'ключ вебхука недействителен — создайте вебхук заново',
    'ACCESS_DENIED': 'у пользователя вебхука нет доступа к этим данным',
    'NOT_FOUND': 'объект не найден',
    'ERROR_METHOD_NOT_FOUND': 'метод не найден — возможно, у вебхука нет прав на этот раздел',
}


class BitrixError(Exception):
    def __init__(self, method: str, code: str, description: str = ''):
        self.method, self.code, self.description = method, code, description
        hint = ERROR_HINTS.get(code, '')
        text = f'{method}: {code}'
        if description:
            text += f' — {description}'
        if hint:
            text += f' ({hint})'
        super().__init__(text)


class ForbiddenMethodError(Exception):
    """Метод не разрешён программой (например, удаление) или запись без --apply."""


@dataclass
class Response:
    result: Any
    next: int | None = None
    total: int | None = None


def build_query(params: dict[str, Any], prefix: str = '') -> str:
    """Параметры в стиле PHP http_build_query: fields[title]=...&select[0]=id — для команд batch."""
    parts: list[str] = []

    def walk(value: Any, key: str) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, f'{key}[{k}]' if key else str(k))
        elif isinstance(value, (list, tuple)):
            for i, v in enumerate(value):
                walk(v, f'{key}[{i}]')
        else:
            if value is None:
                value = ''
            elif isinstance(value, bool):
                value = 'Y' if value else 'N'
            parts.append(f'{quote(key, safe="[]")}={quote(str(value), safe="")}')

    walk(params, prefix)
    return '&'.join(parts)


class RateLimiter:
    def __init__(self, per_second: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.interval = 1.0 / per_second if per_second > 0 else 0
        self.clock, self.sleep = clock, sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            left = self._last + self.interval - self.clock()
            if left > 0:
                self.sleep(left)
        self._last = self.clock()


class BitrixClient:
    def __init__(self, webhook_url: str, *, allow_write: bool = False, requests_per_second: float = 2,
                 timeout: float = 30, max_retries: int = 5, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self._base = webhook_url.rstrip('/') + '/'
        self.allow_write = allow_write
        self.max_retries = max_retries
        self._sleep = sleep
        self._limiter = RateLimiter(requests_per_second, clock=clock, sleep=sleep)
        self._http = httpx.Client(timeout=timeout, transport=transport)
        self.requests_made = 0

    # --- проверка методов ---

    def _check_method(self, method: str) -> None:
        if 'delete' in method.lower() or method not in READ_METHODS | WRITE_METHODS | {'batch'}:
            raise ForbiddenMethodError(f'Метод {method} программе не разрешён.')
        if method in WRITE_METHODS and not self.allow_write:
            raise ForbiddenMethodError(f'Запись ({method}) запрещена: запустите команду с --apply и подтвердите.')

    # --- вызовы ---

    def call(self, method: str, params: dict[str, Any] | None = None) -> Response:
        self._check_method(method)
        if method == 'batch':
            for cmd in (params or {}).get('cmd', {}).values():
                self._check_method(cmd.split('?', 1)[0])
        url = self._base + method + '.json'
        last_problem = ''
        for attempt in range(self.max_retries + 1):
            if attempt:
                pause = 2 ** (attempt - 1)
                log.warning('%s: %s, повтор %d из %d через %d с', method, last_problem, attempt,
                            self.max_retries, pause)
                self._sleep(pause)
            self._limiter.wait()
            self.requests_made += 1
            try:
                r = self._http.post(url, json=params or {})
            except httpx.TimeoutException:
                last_problem = 'таймаут'
                continue
            except httpx.TransportError as e:
                last_problem = f'нет связи с порталом ({type(e).__name__})'
                continue
            try:
                data = r.json()
            except ValueError:
                data = {}
            code = data.get('error') if isinstance(data, dict) else None
            if code in RETRY_ERRORS or (r.status_code >= 500 and not code):
                last_problem = code or f'HTTP {r.status_code}'
                continue
            if code:
                raise BitrixError(method, str(code), str(data.get('error_description', '')))
            if r.status_code >= 400 or 'result' not in data:
                raise BitrixError(method, f'HTTP {r.status_code}', 'неожиданный ответ портала')
            return Response(data['result'], data.get('next'), data.get('total'))
        raise BitrixError(method, 'NO_RESPONSE', f'портал не ответил после {self.max_retries} повторов '
                                                 f'({last_problem})')

    def result(self, method: str, params: dict[str, Any] | None = None) -> Any:
        return self.call(method, params).result

    def iter_list(self, method: str, params: dict[str, Any], key: str | None = None) -> Iterator[Any]:
        """Постраничный обход списочных методов (по 50 записей, параметр start)."""
        start = 0
        while True:
            resp = self.call(method, {**params, 'start': start})
            page = resp.result[key] if key else resp.result
            yield from page
            if resp.next is None:
                return
            start = resp.next

    def batch(self, commands: dict[str, tuple[str, dict[str, Any]]], halt: bool = False) -> tuple[dict, dict]:
        """До 50 команд за запрос. Возвращает (результаты, ошибки) по ключам команд."""
        if len(commands) > BATCH_LIMIT:
            raise ValueError(f'В batch не больше {BATCH_LIMIT} команд, передано {len(commands)}')
        cmd = {key: f'{m}?{build_query(p)}' for key, (m, p) in commands.items()}
        res = self.result('batch', {'halt': 1 if halt else 0, 'cmd': cmd})
        results = res.get('result') or {}
        errors = res.get('result_error') or {}
        # пустые ответы Битрикс отдаёт списком вместо словаря
        return (results if isinstance(results, dict) else {}), (errors if isinstance(errors, dict) else {})

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> 'BitrixClient':
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
