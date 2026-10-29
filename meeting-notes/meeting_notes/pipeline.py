"""Общий конвейер: файл записи → расшифровка → протокол → файлы результата.

Используется и веб-сервером, и командной строкой.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .config import settings
from .export import summary_to_markdown, write_docx
from .summarize import MeetingSummary, Summarizer
from .transcribe import TEXT_EXTENSIONS, Transcriber, Transcript, transcript_from_text

Stage = Callable[[str, str, float], None]  # (стадия, сообщение, доля 0..1)


@dataclass
class Result:
    out_dir: Path
    transcript: Transcript
    summary: Optional[MeetingSummary]
    files: dict[str, Path]


def load_transcript(path: Path, transcriber: Transcriber, language: str, report: Optional[Stage] = None) -> Transcript:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        if report:
            report("transcribe", "Читаю готовую расшифровку", 0.3)
        return transcript_from_text(path.read_text(encoding="utf-8", errors="replace"), path.name)

    if report:
        report("transcribe", f"Загружаю модель Whisper «{transcriber.model_name}»", 0.02)

    def progress(done: float, total: float) -> None:
        if report and total > 0:
            share = min(done / total, 1.0)
            report("transcribe", f"Расшифровка: {int(share * 100)}%", 0.05 + 0.7 * share)

    return transcriber.transcribe(path, language=language, on_progress=progress)


def run_pipeline(
    source: Path,
    out_dir: Path,
    transcriber: Transcriber,
    summarizer: Optional[Summarizer],
    meeting_title: str = "",
    meeting_date: str = "",
    extra_context: str = "",
    language: str = "",
    report: Optional[Stage] = None,
) -> Result:
    out_dir.mkdir(parents=True, exist_ok=True)
    language = language or settings.language

    transcript = load_transcript(source, transcriber, language, report)
    files: dict[str, Path] = {}

    files["transcript_txt"] = out_dir / "transcript.txt"
    files["transcript_txt"].write_text(transcript.with_timestamps() or transcript.text, encoding="utf-8")
    files["transcript_json"] = out_dir / "transcript.json"
    files["transcript_json"].write_text(
        json.dumps(transcript.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if any(s.end for s in transcript.segments):
        files["transcript_srt"] = out_dir / "transcript.srt"
        files["transcript_srt"].write_text(transcript.to_srt(), encoding="utf-8")

    summary: Optional[MeetingSummary] = None
    if summarizer is not None:
        if report:
            report("summarize", "Составляю протокол", 0.8)
        summary = summarizer.summarize(
            transcript,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            extra_context=extra_context,
            on_progress=lambda msg: report and report("summarize", msg, 0.85),
        )
        if meeting_title and not summary.title:
            summary.title = meeting_title

        files["summary_json"] = out_dir / "summary.json"
        files["summary_json"].write_text(summary.model_dump_json(indent=1), encoding="utf-8")
        files["summary_md"] = out_dir / "summary.md"
        files["summary_md"].write_text(
            summary_to_markdown(summary, meeting_date, transcript.source_name), encoding="utf-8"
        )
        if report:
            report("export", "Собираю Word-документ", 0.95)
        files["protocol_docx"] = out_dir / "protocol.docx"
        write_docx(files["protocol_docx"], summary, transcript, meeting_date)

    if report:
        report("done", "Готово", 1.0)
    return Result(out_dir=out_dir, transcript=transcript, summary=summary, files=files)
