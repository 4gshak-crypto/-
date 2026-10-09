"""Транскрибация записи совещания локальной моделью Whisper (faster-whisper).

Модель загружается один раз на процесс и переиспользуется. Запись может быть
аудио или видео в любом формате, который понимает FFmpeg: faster-whisper
декодирует файл сам через PyAV, отдельный ffmpeg не нужен.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wma", ".amr",
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".mpeg", ".mpg", ".3gp",
}
TEXT_EXTENSIONS = {".txt", ".md", ".srt", ".vtt"}

ProgressCallback = Callable[[float, float], None]  # (обработано секунд, всего секунд)


@dataclass
class Segment:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict:
        return {"start": round(self.start, 2), "end": round(self.end, 2), "text": self.text}


@dataclass
class Transcript:
    segments: list[Segment] = field(default_factory=list)
    language: str = ""
    duration: float = 0.0
    source_name: str = ""

    @property
    def text(self) -> str:
        """Сплошной текст без таймкодов."""
        return "\n".join(s.text for s in self.segments if s.text)

    def with_timestamps(self) -> str:
        """Текст с таймкодом в начале каждого фрагмента: `[01:02:03] ...`."""
        return "\n".join(f"[{format_time(s.start)}] {s.text}" for s in self.segments if s.text)

    def to_srt(self) -> str:
        lines = []
        for i, s in enumerate(self.segments, 1):
            lines.append(str(i))
            lines.append(f"{format_time(s.start, srt=True)} --> {format_time(s.end, srt=True)}")
            lines.append(s.text)
            lines.append("")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "duration": round(self.duration, 2),
            "source_name": self.source_name,
            "segments": [s.to_dict() for s in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Transcript":
        return cls(
            segments=[Segment(**s) for s in data.get("segments", [])],
            language=data.get("language", ""),
            duration=float(data.get("duration", 0.0)),
            source_name=data.get("source_name", ""),
        )


def format_time(seconds: float, srt: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    if srt:
        whole = int(secs)
        millis = int(round((secs - whole) * 1000))
        if millis == 1000:
            whole, millis = whole + 1, 0
        return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"
    return f"{hours:02d}:{minutes:02d}:{int(secs):02d}"


class Transcriber:
    """Обёртка над faster-whisper с ленивой загрузкой модели."""

    def __init__(
        self,
        model_name: str = "medium",
        device: str = "auto",
        compute_type: str = "",
        download_root: str = "",
    ):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root or None
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel  # импорт здесь: тяжёлый

                compute_type = self.compute_type or _default_compute_type(self.device)
                self._model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=compute_type,
                    download_root=self.download_root,
                )
        return self._model

    def transcribe(
        self,
        path: Path | str,
        language: Optional[str] = "ru",
        on_progress: Optional[ProgressCallback] = None,
    ) -> Transcript:
        path = Path(path)
        model = self._load()
        segments_iter, info = model.transcribe(
            str(path),
            language=language or None,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,
        )
        return collect_segments(
            segments_iter,
            duration=float(getattr(info, "duration", 0.0) or 0.0),
            language=getattr(info, "language", "") or (language or ""),
            source_name=path.name,
            on_progress=on_progress,
        )


def collect_segments(
    segments_iter: Iterable,
    duration: float,
    language: str,
    source_name: str,
    on_progress: Optional[ProgressCallback] = None,
) -> Transcript:
    """Собирает сегменты из генератора faster-whisper, сообщая о прогрессе."""
    transcript = Transcript(language=language, duration=duration, source_name=source_name)
    for seg in segments_iter:
        text = (seg.text or "").strip()
        if not text:
            continue
        transcript.segments.append(Segment(start=float(seg.start), end=float(seg.end), text=text))
        if on_progress:
            on_progress(float(seg.end), duration)
    if transcript.segments and transcript.duration < transcript.segments[-1].end:
        transcript.duration = transcript.segments[-1].end
    return transcript


def _default_compute_type(device: str) -> str:
    if device == "cuda":
        return "float16"
    if device == "cpu":
        return "int8"
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "float16"
    except Exception:
        pass
    return "int8"


def transcript_from_text(text: str, source_name: str = "") -> Transcript:
    """Готовая расшифровка из текстового файла (.txt, .md, .srt, .vtt).

    Таймкоды SRT/VTT сохраняются; обычный текст разбивается по абзацам или строкам.
    """
    text = text.replace("\r\n", "\n").strip()
    suffix = Path(source_name).suffix.lower()
    if suffix in {".srt", ".vtt"} or "-->" in text:
        return _parse_subtitles(text, source_name)

    segments: list[Segment] = []
    chunks = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(chunks) <= 1:
        chunks = [line.strip() for line in text.split("\n") if line.strip()]
    for chunk in chunks:
        segments.append(Segment(start=0.0, end=0.0, text=" ".join(chunk.split())))
    return Transcript(segments=segments, language="", duration=0.0, source_name=source_name)


def _parse_subtitles(text: str, source_name: str) -> Transcript:
    import re

    time_re = re.compile(
        r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
    )

    def to_sec(h, m, s, ms) -> float:
        return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000

    segments: list[Segment] = []
    current: Optional[Segment] = None
    for line in text.split("\n"):
        line = line.strip()
        match = time_re.search(line)
        if match:
            if current and current.text:
                segments.append(current)
            g = match.groups()
            current = Segment(start=to_sec(*g[:4]), end=to_sec(*g[4:]), text="")
            continue
        if not line or line.isdigit() or line.upper().startswith("WEBVTT"):
            continue
        if current is not None:
            current.text = (current.text + " " + line).strip() if current.text else line
    if current and current.text:
        segments.append(current)
    duration = segments[-1].end if segments else 0.0
    return Transcript(segments=segments, language="", duration=duration, source_name=source_name)
