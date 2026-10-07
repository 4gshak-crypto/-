"""Локальный веб-сервер: загрузка записи, очередь задач, просмотр и скачивание протокола.

Задачи выполняются по одной в фоновом потоке: расшифровка занимает процессор
целиком, параллельные запуски только мешают друг другу. Состояние каждой
задачи лежит в `data/jobs/<id>/job.json`, поэтому история переживает перезапуск.
"""

from __future__ import annotations

import json
import queue
import re
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import __version__
from .config import settings
from .pipeline import run_pipeline
from .summarize import Summarizer, describe_api_error
from .transcribe import AUDIO_EXTENSIONS, TEXT_EXTENSIONS, Transcriber

STATIC_DIR = Path(__file__).parent / "static"
JOBS_DIR = settings.data_dir / "jobs"

DOWNLOADS = {
    "summary_md": ("summary.md", "text/markdown; charset=utf-8"),
    "summary_json": ("summary.json", "application/json"),
    "protocol_docx": ("protocol.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "transcript_txt": ("transcript.txt", "text/plain; charset=utf-8"),
    "transcript_srt": ("transcript.srt", "text/plain; charset=utf-8"),
    "transcript_json": ("transcript.json", "application/json"),
}


@dataclass
class Job:
    id: str
    created_at: float
    source_name: str
    meeting_title: str = ""
    meeting_date: str = ""
    extra_context: str = ""
    language: str = "ru"
    want_summary: bool = True
    status: str = "queued"  # queued | running | done | error
    stage: str = ""
    message: str = "В очереди"
    progress: float = 0.0
    error: str = ""
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    files: list[str] = field(default_factory=list)
    duration: float = 0.0

    @property
    def dir(self) -> Path:
        return JOBS_DIR / self.id

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "job.json").write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Job":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def public(self, with_result: bool = False) -> dict:
        data = asdict(self)
        data.pop("extra_context", None)
        if with_result and self.status == "done":
            summary_path = self.dir / "summary.json"
            transcript_path = self.dir / "transcript.json"
            data["summary"] = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else None
            data["transcript"] = json.loads(transcript_path.read_text(encoding="utf-8")) if transcript_path.is_file() else None
        return data


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.queue: "queue.Queue[str]" = queue.Queue()
        self.transcriber = Transcriber(
            model_name=settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            download_root=settings.whisper_download_root,
        )
        self._summarizer: Optional[Summarizer] = None
        self._load_existing()
        self.worker = threading.Thread(target=self._work, name="meeting-notes-worker", daemon=True)
        self.worker.start()

    def _load_existing(self) -> None:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        for job_file in JOBS_DIR.glob("*/job.json"):
            try:
                job = Job.load(job_file)
            except Exception:
                continue
            if job.status in ("queued", "running"):
                job.status = "error"
                job.error = "Сервер был остановлен во время обработки. Загрузите запись ещё раз."
                job.save()
            self.jobs[job.id] = job

    @property
    def summarizer(self) -> Summarizer:
        if self._summarizer is None:
            self._summarizer = Summarizer()
        return self._summarizer

    def submit(self, job: Job) -> None:
        with self.lock:
            self.jobs[job.id] = job
        job.save()
        self.queue.put(job.id)

    def delete(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return False
            if job.status == "running":
                raise HTTPException(409, "Задача сейчас выполняется, удалить её нельзя.")
            del self.jobs[job_id]
        shutil.rmtree(job.dir, ignore_errors=True)
        return True

    def _work(self) -> None:
        while True:
            job_id = self.queue.get()
            job = self.jobs.get(job_id)
            if job is None:
                continue
            self._run(job)

    def _run(self, job: Job) -> None:
        job.status = "running"
        job.started_at = time.time()
        job.message = "Начинаю"
        job.save()
        last_save = [0.0]

        def report(stage: str, message: str, share: float) -> None:
            job.stage, job.message, job.progress = stage, message, share
            now = time.time()
            if now - last_save[0] > 2 or share >= 1.0:
                job.save()
                last_save[0] = now

        source = next((p for p in job.dir.iterdir() if p.name.startswith("source")), None)
        try:
            if source is None:
                raise FileNotFoundError("Файл записи не найден")
            summarizer = self.summarizer if job.want_summary else None
            result = run_pipeline(
                source,
                job.dir,
                self.transcriber,
                summarizer,
                meeting_title=job.meeting_title,
                meeting_date=job.meeting_date,
                extra_context=job.extra_context,
                language=job.language,
                report=report,
            )
            job.files = sorted(result.files.keys())
            job.duration = result.transcript.duration
            if result.summary and not job.meeting_title:
                job.meeting_title = result.summary.title
            job.status = "done"
            job.message = "Готово"
            job.progress = 1.0
        except Exception as exc:  # noqa: BLE001 - причину нужно показать в интерфейсе
            job.status = "error"
            job.error = describe_api_error(exc)
            job.message = "Ошибка"
            # Расшифровка могла успеть сохраниться: отдадим хотя бы её.
            job.files = sorted(k for k, (name, _) in DOWNLOADS.items() if (job.dir / name).is_file())
        finally:
            job.finished_at = time.time()
            job.save()


manager: Optional[JobManager] = None


@asynccontextmanager
async def _lifespan(_: FastAPI):
    global manager
    manager = JobManager()
    yield


app = FastAPI(title="Протокол совещания", version=__version__, lifespan=_lifespan)


def _manager() -> JobManager:
    assert manager is not None
    return manager


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict:
    return {
        "version": __version__,
        "whisper_model": settings.whisper_model,
        "claude_model": settings.claude_model,
        "has_api_key": settings.has_api_key,
        "max_upload_mb": settings.max_upload_mb,
        "formats": sorted(AUDIO_EXTENSIONS | TEXT_EXTENSIONS),
    }


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    jobs = sorted(_manager().jobs.values(), key=lambda j: j.created_at, reverse=True)
    return [j.public() for j in jobs]


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    title: str = Form(""),
    date: str = Form(""),
    context: str = Form(""),
    language: str = Form("ru"),
    summarize: str = Form("1"),
) -> JSONResponse:
    name = Path(file.filename or "запись").name
    suffix = Path(name).suffix.lower()
    if suffix not in AUDIO_EXTENSIONS | TEXT_EXTENSIONS:
        raise HTTPException(400, f"Формат «{suffix or 'без расширения'}» не поддерживается.")
    want_summary = summarize not in ("0", "false", "off", "")
    if want_summary and not settings.has_api_key:
        raise HTTPException(
            400,
            "Не задан ключ Claude API (ANTHROPIC_API_KEY). Добавьте его в .env и перезапустите сервер, "
            "либо снимите галочку «Составить протокол», чтобы получить только расшифровку.",
        )

    job = Job(
        id=time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
        created_at=time.time(),
        source_name=name,
        meeting_title=title.strip()[:200],
        meeting_date=date.strip()[:40],
        extra_context=context.strip()[:4000],
        language=(re.sub(r"[^a-z]", "", language.lower()) or "ru")[:5],
        want_summary=want_summary,
    )
    job.dir.mkdir(parents=True, exist_ok=True)
    target = job.dir / ("source" + suffix)
    limit = settings.max_upload_mb * 1024 * 1024
    written = 0
    with target.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > limit:
                out.close()
                shutil.rmtree(job.dir, ignore_errors=True)
                raise HTTPException(413, f"Файл больше {settings.max_upload_mb} МБ.")
            out.write(chunk)
    if written == 0:
        shutil.rmtree(job.dir, ignore_errors=True)
        raise HTTPException(400, "Пустой файл.")

    _manager().submit(job)
    return JSONResponse(job.public(), status_code=202)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = _manager().jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Задача не найдена")
    return job.public(with_result=True)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    if not _manager().delete(job_id):
        raise HTTPException(404, "Задача не найдена")
    return {"ok": True}


@app.get("/api/jobs/{job_id}/files/{kind}")
def download(job_id: str, kind: str) -> FileResponse:
    job = _manager().jobs.get(job_id)
    if job is None or kind not in DOWNLOADS:
        raise HTTPException(404, "Файл не найден")
    name, media_type = DOWNLOADS[kind]
    path = job.dir / name
    if not path.is_file():
        raise HTTPException(404, "Файл ещё не готов")
    stem = re.sub(r"[^\w\-]+", "_", (job.meeting_title or Path(job.source_name).stem), flags=re.UNICODE).strip("_") or "протокол"
    return FileResponse(path, media_type=media_type, filename=f"{stem}_{name}")


def main() -> None:
    print(f"Протокол совещания {__version__}: http://{settings.host}:{settings.port}")
    print(f"Whisper: {settings.whisper_model}; Claude: {settings.claude_model}; ключ API: {'есть' if settings.has_api_key else 'НЕТ'}")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
