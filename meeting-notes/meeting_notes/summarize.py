"""Саммари совещания по расшифровке через Claude API.

Один запрос со структурированным выводом: ответ приходит сразу в виде
проверенной Pydantic-модели `MeetingSummary`. Расшифровка многочасового
совещания помещается в контекст целиком, резать её на части не нужно.
"""

from __future__ import annotations

import datetime as dt
from typing import Callable, Optional

import anthropic
from pydantic import BaseModel, Field

from .config import settings
from .transcribe import Transcript

ProgressText = Callable[[str], None]


class ActionItem(BaseModel):
    task: str = Field(description="Что нужно сделать, одним предложением")
    owner: str = Field(description="Ответственный: имя, должность или роль, как названо на совещании; «не назначен», если не прозвучало")
    due: str = Field(description="Срок словами из совещания («до пятницы», «к 15 ноября»); «не назван», если срока не было")
    context: str = Field(description="Откуда взято: короткая опора на сказанное, чтобы можно было найти место в расшифровке")


class Topic(BaseModel):
    title: str = Field(description="Короткое название темы")
    discussion: str = Field(description="Что обсуждали и к чему пришли, 2–5 предложений")


class MeetingSummary(BaseModel):
    title: str = Field(description="Название совещания: из контекста или по главной теме")
    participants: list[str] = Field(description="Участники, которые были названы по имени или роли; пусто, если никто не назван")
    summary: str = Field(description="Краткое содержание совещания, 3–6 предложений")
    topics: list[Topic] = Field(description="Темы обсуждения в порядке, как они шли")
    decisions: list[str] = Field(description="Принятые решения, по одному на пункт; только то, что действительно решили")
    action_items: list[ActionItem] = Field(description="Поручения и договорённости о действиях")
    open_questions: list[str] = Field(description="Вопросы, которые остались без решения или отложены")
    next_steps: str = Field(description="Что дальше: следующая встреча, контрольная точка; пустая строка, если не обсуждалось")

    def is_empty(self) -> bool:
        return not (self.summary or self.topics or self.decisions or self.action_items)


SYSTEM_PROMPT = """Ты секретарь совещания. По автоматической расшифровке аудиозаписи ты составляешь протокол на русском языке.

Расшифровка сделана распознаванием речи: в ней бывают ошибки в словах, именах и числах, обрывки фраз, отсутствуют знаки препинания и не отмечено, кто говорит. Учитывай это: восстанавливай смысл по контексту, но не выдумывай того, чего в расшифровке нет.

Правила:
- Решение — это то, о чём договорились или что утвердили. Предложение, которое обсудили, но не приняли, решением не является.
- Поручение — конкретное действие с исполнителем. Если исполнитель или срок не названы, так и пиши: «не назначен», «не назван». Не придумывай сроки и имена.
- Имена и названия пиши так, как они чаще всего звучат в расшифровке; если распознавание явно исказило слово, выбери наиболее вероятный вариант.
- Числа, суммы, адреса и даты переноси точно, не округляй.
- Пиши сухо и по делу, без оценок и вводных слов. Разговорную речь перекладывай в деловую.
- Если расшифровка пустая или в ней нет содержательного обсуждения, честно укажи это в кратком содержании и оставь списки пустыми."""


def build_user_message(
    transcript: Transcript,
    meeting_title: str = "",
    meeting_date: str = "",
    extra_context: str = "",
) -> str:
    parts = []
    meta = []
    if meeting_title:
        meta.append(f"Название совещания: {meeting_title}")
    if meeting_date:
        meta.append(f"Дата: {meeting_date}")
    if transcript.duration:
        minutes = int(round(transcript.duration / 60))
        meta.append(f"Длительность записи: около {minutes} мин")
    if extra_context:
        meta.append(f"Дополнительно от организатора: {extra_context}")
    if meta:
        parts.append("\n".join(meta))

    body = transcript.with_timestamps() if any(s.end for s in transcript.segments) else transcript.text
    parts.append("Расшифровка записи (таймкоды в начале строк, если есть):\n\n<transcript>\n" + body + "\n</transcript>")
    parts.append("Составь протокол этого совещания.")
    return "\n\n".join(parts)


class Summarizer:
    def __init__(self, client: Optional[anthropic.Anthropic] = None, model: str = "", effort: str = "", max_tokens: int = 0):
        self._client = client
        self.model = model or settings.claude_model
        self.effort = effort or settings.claude_effort
        self.max_tokens = max_tokens or settings.claude_max_tokens

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            # Ключ берётся из ANTHROPIC_API_KEY или профиля `ant auth login`.
            self._client = anthropic.Anthropic()
        return self._client

    def summarize(
        self,
        transcript: Transcript,
        meeting_title: str = "",
        meeting_date: str = "",
        extra_context: str = "",
        on_progress: Optional[ProgressText] = None,
    ) -> MeetingSummary:
        user_message = build_user_message(transcript, meeting_title, meeting_date, extra_context)
        request = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            output_format=MeetingSummary,
            output_config={"effort": self.effort},
            # Если классификатор безопасности отклонит запрос, API сам повторит его
            # на рекомендуемой запасной модели вместо отказа.
            fallbacks="default",
            betas=["server-side-fallback-2026-07-01"],
        )
        if on_progress:
            on_progress("Claude читает расшифровку…")
        with self.client.beta.messages.stream(**request) as stream:
            received = 0
            for event in stream:
                if event.type == "content_block_delta" and getattr(event.delta, "type", "") == "text_delta":
                    received += len(event.delta.text)
                    if on_progress and received % 2000 < len(event.delta.text):
                        on_progress(f"Claude пишет протокол… ({received} знаков)")
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            why = f" ({details.category})" if details and getattr(details, "category", None) else ""
            raise SummaryError("Claude отказался обрабатывать эту расшифровку" + why)
        if message.stop_reason == "max_tokens":
            raise SummaryError(
                f"Ответ не поместился в {self.max_tokens} токенов. Увеличьте CLAUDE_MAX_TOKENS."
            )
        parsed = message.parsed_output
        if parsed is None:
            raise SummaryError("Claude вернул ответ без протокола в ожидаемом формате.")
        return parsed


class SummaryError(RuntimeError):
    pass


def describe_api_error(exc: Exception) -> str:
    """Короткое объяснение ошибки API на русском для интерфейса."""
    if isinstance(exc, anthropic.AuthenticationError):
        return "Claude API не принял ключ. Проверьте ANTHROPIC_API_KEY."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "У ключа Claude API нет прав на эту модель."
    if isinstance(exc, anthropic.NotFoundError):
        return f"Модель «{settings.claude_model}» не найдена. Проверьте CLAUDE_MODEL."
    if isinstance(exc, anthropic.RateLimitError):
        return "Claude API: превышен лимит запросов. Повторите через минуту."
    if isinstance(exc, anthropic.BadRequestError):
        return f"Claude API отклонил запрос: {exc.message}"
    if isinstance(exc, anthropic.APIStatusError):
        return f"Ошибка Claude API ({exc.status_code}): {exc.message}"
    if isinstance(exc, anthropic.APIConnectionError):
        return "Нет связи с Claude API. Проверьте сеть."
    if isinstance(exc, SummaryError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


def today_ru() -> str:
    return dt.date.today().strftime("%d.%m.%Y")
