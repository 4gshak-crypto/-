"""Transcriber вызывает faster-whisper с правильными аргументами (сама модель подменена)."""

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

from meeting_notes.transcribe import Transcriber


class FakeWhisperModel:
    created = []

    def __init__(self, model_size_or_path, device="auto", compute_type="default", download_root=None, **kw):
        FakeWhisperModel.created.append((model_size_or_path, device, compute_type, download_root))

    def transcribe(self, audio, **kwargs):
        self.kwargs = kwargs
        segs = iter([SimpleNamespace(start=0.0, end=1.5, text=" Привет "), SimpleNamespace(start=1.5, end=4.0, text="Начинаем")])
        return segs, SimpleNamespace(duration=4.0, language="ru")


def test_transcriber_lazy_load_and_arguments(monkeypatch, tmp_path: Path):
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))
    FakeWhisperModel.created.clear()
    t = Transcriber(model_name="small", device="cpu", download_root=str(tmp_path))
    assert FakeWhisperModel.created == []  # модель не грузится до первого вызова

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    seen = []
    result = t.transcribe(audio, language="ru", on_progress=lambda d, tot: seen.append((d, tot)))
    assert FakeWhisperModel.created == [("small", "cpu", "int8", str(tmp_path))]
    assert [s.text for s in result.segments] == ["Привет", "Начинаем"]
    assert result.duration == 4.0 and result.language == "ru" and result.source_name == "a.wav"
    assert seen == [(1.5, 4.0), (4.0, 4.0)]

    t.transcribe(audio, language=None)
    assert len(FakeWhisperModel.created) == 1  # повторно не загружается


def test_arguments_match_real_faster_whisper_signature():
    """Имена аргументов, которые мы передаём, существуют в установленной faster-whisper."""
    from faster_whisper import WhisperModel

    params = inspect.signature(WhisperModel.transcribe).parameters
    for name in ("language", "beam_size", "vad_filter", "vad_parameters", "condition_on_previous_text"):
        assert name in params
    init = inspect.signature(WhisperModel.__init__).parameters
    for name in ("device", "compute_type", "download_root"):
        assert name in init
