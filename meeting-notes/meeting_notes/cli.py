"""Командная строка: `python -m meeting_notes.cli запись.mp3 [--out папка]`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import settings
from .pipeline import run_pipeline
from .summarize import Summarizer, describe_api_error
from .transcribe import Transcriber


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="meeting-notes",
        description="Расшифровка записи совещания и протокол с решениями и поручениями.",
    )
    parser.add_argument("source", help="аудио, видео или готовая расшифровка (.txt/.srt/.vtt)")
    parser.add_argument("--out", "-o", help="папка результата (по умолчанию рядом с записью)")
    parser.add_argument("--title", default="", help="название совещания")
    parser.add_argument("--date", default="", help="дата совещания, например 07.10.2026")
    parser.add_argument("--context", default="", help="подсказка для протокола: участники, повестка")
    parser.add_argument("--language", default=settings.language, help="язык речи (по умолчанию ru)")
    parser.add_argument("--whisper-model", default=settings.whisper_model, help="модель Whisper: tiny, base, small, medium, large-v3")
    parser.add_argument("--no-summary", action="store_true", help="только расшифровка, без Claude")
    args = parser.parse_args(argv)

    source = Path(args.source)
    if not source.is_file():
        print(f"Файл не найден: {source}", file=sys.stderr)
        return 2
    out_dir = Path(args.out) if args.out else source.parent / (source.stem + "_протокол")

    transcriber = Transcriber(
        model_name=args.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        download_root=settings.whisper_download_root,
    )
    summarizer = None
    if not args.no_summary:
        if not settings.has_api_key:
            print(
                "Не задан ANTHROPIC_API_KEY: будет только расшифровка. "
                "Укажите ключ в .env или добавьте --no-summary, чтобы убрать это сообщение.",
                file=sys.stderr,
            )
        else:
            summarizer = Summarizer()

    def report(stage: str, message: str, share: float) -> None:
        print(f"[{int(share * 100):3d}%] {message}", file=sys.stderr, flush=True)

    try:
        result = run_pipeline(
            source,
            out_dir,
            transcriber,
            summarizer,
            meeting_title=args.title,
            meeting_date=args.date,
            extra_context=args.context,
            language=args.language,
            report=report,
        )
    except Exception as exc:  # noqa: BLE001 - показать человеку причину
        print("Ошибка: " + describe_api_error(exc), file=sys.stderr)
        return 1

    if result.summary:
        print(result.files["summary_md"].read_text(encoding="utf-8"))
    else:
        print(result.transcript.with_timestamps() or result.transcript.text)
    print(f"\nФайлы сохранены в {result.out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
