FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MEDIA_CLOUD=1 MEDIA_NO_BROWSER=1 MEDIA_DOWNLOAD_DIR=/tmp/mediadownloader
WORKDIR /app
# FFmpeg de sistema inclui ffprobe (necessario para unir/verificar audio e video).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
COPY requirements-cloud.txt ./
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements-cloud.txt \
    && python -m pip check \
    && python -m yt_dlp --version
COPY server.py ./
COPY web/ ./web/
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]
