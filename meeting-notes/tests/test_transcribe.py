from types import SimpleNamespace

from meeting_notes.transcribe import Transcript, collect_segments, format_time, transcript_from_text


def test_format_time():
    assert format_time(0) == "00:00:00"
    assert format_time(3725.6) == "01:02:05"
    assert format_time(61.5, srt=True) == "00:01:01,500"
    assert format_time(1.9996, srt=True) == "00:00:02,000"


def test_collect_segments_skips_empty_and_reports_progress():
    fake = [
        SimpleNamespace(start=0.0, end=2.5, text=" Добрый день "),
        SimpleNamespace(start=2.5, end=3.0, text="   "),
        SimpleNamespace(start=3.0, end=7.0, text="Начнём с ремонта кровли"),
    ]
    seen = []
    t = collect_segments(iter(fake), duration=10.0, language="ru", source_name="a.mp3",
                         on_progress=lambda done, total: seen.append((done, total)))
    assert [s.text for s in t.segments] == ["Добрый день", "Начнём с ремонта кровли"]
    assert seen == [(2.5, 10.0), (7.0, 10.0)]
    assert t.text == "Добрый день\nНачнём с ремонта кровли"
    assert t.with_timestamps().startswith("[00:00:00] Добрый день")
    assert "00:00:03,000 --> 00:00:07,000" in t.to_srt()
    assert Transcript.from_dict(t.to_dict()).segments[1].end == 7.0


def test_transcript_from_plain_text_paragraphs():
    t = transcript_from_text("Первый абзац\nпродолжение.\n\nВторой абзац.", "notes.txt")
    assert [s.text for s in t.segments] == ["Первый абзац продолжение.", "Второй абзац."]
    assert t.duration == 0.0
    assert t.with_timestamps().startswith("[00:00:00]")


def test_transcript_from_srt():
    srt = """1
00:00:01,000 --> 00:00:04,000
Здравствуйте, коллеги.

2
00:01:00,500 --> 00:01:03,000
Переходим к адресу
Ленина, 5.
"""
    t = transcript_from_text(srt, "meeting.srt")
    assert len(t.segments) == 2
    assert t.segments[1].start == 60.5
    assert t.segments[1].text == "Переходим к адресу Ленина, 5."
    assert t.duration == 63.0


def test_transcript_from_vtt():
    vtt = "WEBVTT\n\n00:00.000 --> 00:02.000\nПривет\n\n00:02.000 --> 00:05.500\nПока\n"
    t = transcript_from_text(vtt, "m.vtt")
    assert [s.text for s in t.segments] == ["Привет", "Пока"]
    assert t.segments[1].end == 5.5
