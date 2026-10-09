FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY meeting_notes ./meeting_notes

ENV MEETING_HOST=0.0.0.0 \
    MEETING_PORT=8787 \
    MEETING_DATA_DIR=/data \
    WHISPER_DOWNLOAD_ROOT=/models
VOLUME ["/data", "/models"]
EXPOSE 8787

CMD ["python", "-m", "meeting_notes"]
