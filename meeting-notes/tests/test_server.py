"""Проверка веб-сервера целиком: загрузка готовой расшифровки, очередь, результат, скачивание.

Whisper не вызывается (входит текстовый файл), Claude подменён: возвращает готовый протокол.
"""

import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from meeting_notes import config

    monkeypatch.setattr(config.settings, "data_dir", tmp_path / "data")
    import importlib

    from meeting_notes import server

    importlib.reload(server)
    monkeypatch.setattr(server, "JOBS_DIR", tmp_path / "data" / "jobs")

    from tests.test_summarize_export import sample_summary

    class FakeSummarizer:
        def summarize(self, transcript, meeting_title="", meeting_date="", extra_context="", on_progress=None):
            assert "Ленина" in transcript.text
            if on_progress:
                on_progress("пишу")
            s = sample_summary()
            s.title = meeting_title or s.title
            return s

    monkeypatch.setattr(server.JobManager, "summarizer", property(lambda self: FakeSummarizer()))

    from fastapi.testclient import TestClient

    with TestClient(server.app) as c:
        yield c


def wait_done(client, job_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.1)
    raise AssertionError("задача не завершилась")


def test_health(client):
    data = client.get("/api/health").json()
    assert data["has_api_key"] is True
    assert ".mp3" in data["formats"] and ".srt" in data["formats"]


def test_full_flow_with_text_transcript(client):
    text = "Добрый день.\n\nПо адресу Ленина, 5 акт по кровле сделаем к пятнице.\n"
    r = client.post(
        "/api/jobs",
        files={"file": ("planerka.txt", text.encode("utf-8"), "text/plain")},
        data={"title": "Планёрка", "date": "07.10.2026", "context": "Участники: Иванов", "language": "ru", "summarize": "1"},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]

    job = wait_done(client, job_id)
    assert job["status"] == "done", job
    assert job["summary"]["title"] == "Планёрка"
    assert job["transcript"]["segments"][1]["text"].startswith("По адресу Ленина")
    assert set(job["files"]) >= {"summary_md", "protocol_docx", "summary_json", "transcript_txt", "transcript_json"}
    assert "transcript_srt" not in job["files"]  # у текста без таймкодов субтитров нет
    assert "extra_context" not in job

    md = client.get(f"/api/jobs/{job_id}/files/summary_md")
    assert md.status_code == 200 and "## Поручения" in md.text
    assert "attachment" in md.headers["content-disposition"]
    docx = client.get(f"/api/jobs/{job_id}/files/protocol_docx")
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    assert client.get(f"/api/jobs/{job_id}/files/transcript_srt").status_code == 404

    listing = client.get("/api/jobs").json()
    assert listing[0]["id"] == job_id and listing[0]["meeting_title"] == "Планёрка"

    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_transcript_only_with_srt(client):
    srt = "1\n00:00:01,000 --> 00:00:03,000\nЛенина пять\n"
    r = client.post("/api/jobs", files={"file": ("m.srt", srt.encode(), "text/plain")}, data={"summarize": "0"})
    assert r.status_code == 202
    job = wait_done(client, r.json()["id"])
    assert job["status"] == "done"
    assert job["summary"] is None
    assert "transcript_srt" in job["files"] and "summary_md" not in job["files"]
    assert job["duration"] == 3.0


def test_rejects_bad_format_and_empty_file(client):
    r = client.post("/api/jobs", files={"file": ("x.exe", b"abc", "application/octet-stream")})
    assert r.status_code == 400 and "не поддерживается" in r.json()["detail"]
    r = client.post("/api/jobs", files={"file": ("x.mp3", b"", "audio/mpeg")})
    assert r.status_code == 400 and "Пустой" in r.json()["detail"]


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Протокол совещания" in r.text
