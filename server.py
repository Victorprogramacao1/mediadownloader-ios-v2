"""MediaDownloader Local v1.6 - YouTube authorized media downloader for Windows.
Local-only FastAPI application. No external conversion API.
"""
from __future__ import annotations

import asyncio
import importlib.util
from importlib import metadata as package_metadata
import json
import os
import queue
import re
import secrets
import base64
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'
DOWNLOADS = Path(os.getenv('MEDIA_DOWNLOAD_DIR', str(ROOT / 'downloads'))).resolve()
DOWNLOADS.mkdir(parents=True, exist_ok=True)
MAX_JOBS = 500
CLOUD = os.getenv('MEDIA_CLOUD', '0') == '1'
MAX_BATCH_URLS = min(100, max(1, int(os.getenv('MEDIA_MAX_BATCH_URLS', '20' if CLOUD else '100'))))
MAX_DISK_MB = max(100, int(os.getenv('MEDIA_MAX_DISK_MB', '900' if CLOUD else '250000')))
MAX_FILE_MB = max(20, int(os.getenv('MEDIA_MAX_FILE_MB', '300' if CLOUD else '1500')))
APP_PASSWORD = os.getenv('APP_PASSWORD', '')
if CLOUD and (len(APP_PASSWORD) < 12 or APP_PASSWORD == 'troque-esta-senha'):
    raise RuntimeError('Na nuvem configure APP_PASSWORD com pelo menos 12 caracteres nas variáveis de ambiente.')
BATCHES: dict[str, dict] = {}
JOBS: dict[str, dict] = {}
LOCK = threading.RLock()
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='media')
VERSION = '1.8.0'

app = FastAPI(title='MediaDownloader Local', version=VERSION, docs_url=None, redoc_url=None)
app.mount('/assets', StaticFiles(directory=WEB), name='assets')

@app.middleware('http')
async def require_password(request, call_next):
    # Authentication is mandatory on Render; browser-native Basic auth also protects
    # assets, API, progress endpoints, files and ZIP links.
    if request.url.path == '/api/health':
        return await call_next(request)
    if APP_PASSWORD:
        header = request.headers.get('authorization', '')
        valid = False
        if header.startswith('Basic '):
            try:
                decoded = base64.b64decode(header[6:], validate=True).decode('utf-8')
                username, password = decoded.split(':', 1)
                valid = secrets.compare_digest(username, 'admin') and secrets.compare_digest(password, APP_PASSWORD)
            except (ValueError, UnicodeDecodeError):
                pass
        if not valid:
            return JSONResponse({'detail': 'Acesso restrito. Informe o usuário admin e a senha configurada.'},
                                status_code=401, headers={'WWW-Authenticate': 'Basic realm="MediaDownloader"'})
    return await call_next(request)



class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)

class DownloadRequest(AnalyzeRequest):
    format: str = 'mp4'
    quality: int = 1080
    authorized: bool = False

class BatchRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=MAX_BATCH_URLS)
    format: str = 'mp4'
    quality: int = 1080
    authorized: bool = False

ALLOWED_HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'www.youtu.be'}

def validate_url(raw: str) -> str:
    url = raw.strip()
    if not url or any(c.isspace() for c in url):
        raise ValueError('Informe um link válido, sem espaços.')
    try:
        parts = urlparse(url)
        host = (parts.hostname or '').lower()
        if parts.scheme != 'https' or host not in ALLOWED_HOSTS or parts.username or parts.password or parts.port:
            raise ValueError('Aceitamos apenas links HTTPS do YouTube.')
        if not parts.path or parts.path == '/':
            raise ValueError('Informe o endereço de um vídeo, não a página inicial.')
        if host.endswith('youtu.be'):
            video_id = parts.path.strip('/').split('/')[0]
        elif parts.path == '/watch':
            from urllib.parse import parse_qs
            video_id = parse_qs(parts.query).get('v', [''])[0]
        elif parts.path.startswith(('/shorts/', '/live/', '/embed/')):
            video_id = parts.path.split('/')[2]
        else:
            raise ValueError('Use um link de vídeo, Shorts ou transmissão do YouTube.')
        if not re.fullmatch(r'[\w-]{11}', video_id):
            raise ValueError('O identificador do vídeo não é válido.')
        return 'https://www.youtube.com/watch?v=' + video_id
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Não foi possível interpretar o endereço.') from exc

def ffmpeg_path() -> str | None:
    try:
        import imageio_ffmpeg
        filename = imageio_ffmpeg.get_ffmpeg_exe()
        if filename and Path(filename).is_file():
            return str(Path(filename).resolve())
    except Exception:
        pass
    return shutil.which('ffmpeg')

def ytdlp_ready() -> bool:
    return importlib.util.find_spec('yt_dlp') is not None

def base_cmd() -> list[str]:
    cmd = [sys.executable, '-m', 'yt_dlp', '--no-playlist', '--no-warnings', '--newline']
    ff = ffmpeg_path()
    if ff:
        cmd += ['--ffmpeg-location', ff]
    return cmd

def safe_error(message: str) -> str:
    lowered = message.lower()
    if 'sign in to confirm' in lowered and 'not a bot' in lowered:
        return ('O YouTube recusou a solicitação automática do servidor e exige verificação de acesso. '
                'Isso não é uma falha na fila ou no MP4; atualizar bibliotecas não garante acesso ao vídeo.')
    output = message.strip().splitlines()
    line = next((l for l in reversed(output) if 'ERROR:' in l), output[-1] if output else '')
    line = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
    return line[-420:] or 'Ocorreu uma falha no processamento. Atualize o aplicativo e tente novamente.'

@app.get('/')
def index():
    return FileResponse(WEB / 'index.html')

@app.get('/api/health')
def health():
    return {'version': VERSION, 'local': not CLOUD, 'yt_dlp': ytdlp_ready(), 'ffmpeg': bool(ffmpeg_path()), 'downloads_folder': 'temporaria' if CLOUD else str(DOWNLOADS), 'max_batch_urls': MAX_BATCH_URLS, 'cloud': CLOUD}

def installed_version(distribution: str) -> str | None:
    try:
        return package_metadata.version(distribution)
    except package_metadata.PackageNotFoundError:
        return None


@app.get('/api/engine')
def engine_details():
    """Requer autenticação Basic na nuvem; informa versões efetivamente instaladas."""
    ffmpeg = ffmpeg_path()
    ffmpeg_version = None
    if ffmpeg:
        try:
            result = subprocess.run([ffmpeg, '-version'], capture_output=True, text=True,
                                    timeout=5, encoding='utf-8', errors='replace')
            ffmpeg_version = result.stdout.splitlines()[0][:150] if result.stdout else None
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {'app_version': VERSION, 'yt_dlp': installed_version('yt-dlp'),
            'fastapi': installed_version('fastapi'), 'uvicorn': installed_version('uvicorn'),
            'imageio_ffmpeg': installed_version('imageio-ffmpeg'), 'ffmpeg': ffmpeg_version,
            'python': sys.version.split()[0], 'cloud': CLOUD}


@app.post('/api/analyze')
async def analyze(payload: AnalyzeRequest):
    try:
        url = validate_url(payload.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not ytdlp_ready():
        raise HTTPException(503, 'yt-dlp não instalado. Execute INICIAR_WINDOWS.bat para instalar as dependências.')

    def extract():
        cmd = base_cmd() + ['--dump-single-json', '--skip-download', url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=80, encoding='utf-8', errors='replace')
        if result.returncode != 0:
            raise RuntimeError(safe_error(result.stderr or result.stdout))
        return json.loads(result.stdout)
    try:
        info = await asyncio.to_thread(extract)
        if info.get('_type') == 'playlist':
            raise RuntimeError('Playlists não são suportadas nesta versão.')
        if info.get('is_live'):
            raise RuntimeError('Transmissões ao vivo não são suportadas nesta versão.')
        return {
            'id': str(info.get('id', '')),
            'title': str(info.get('title', 'Vídeo sem título'))[:180],
            'uploader': str(info.get('uploader', ''))[:110],
            'duration': info.get('duration'),
            'thumbnail': info.get('thumbnail'),
            'url': url,
        }
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, 'A análise demorou demais. Tente novamente.') from exc
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(422, str(exc)[:420]) from exc

def validate_settings(media_format: str, quality: int, authorized: bool) -> None:
    if not authorized:
        raise HTTPException(400, 'Confirme que tem autorização para baixar os conteúdos.')
    if media_format not in {'mp4', 'mp3'}:
        raise HTTPException(400, 'Formato não suportado.')
    if quality not in {360, 720, 1080}:
        raise HTTPException(400, 'Qualidade não suportada.')

def verify_engine() -> None:
    if not ytdlp_ready() or not ffmpeg_path():
        raise HTTPException(503, 'Dependências ausentes. Execute INICIAR_WINDOWS.bat.')

def ensure_capacity() -> None:
    # Soft cap: prevents filling a small ephemeral filesystem with queued files.
    if CLOUD:
        used = sum(f.stat().st_size for f in DOWNLOADS.rglob('*') if f.is_file())
        if used >= MAX_DISK_MB * 1024 * 1024:
            raise HTTPException(507, 'Espaço temporário esgotado. Salve seu lote e reinicie o serviço para liberar espaço.')


def prune_old_jobs(required: int = 1) -> None:
    """Must be called while holding LOCK; never delete running task metadata."""
    for key in list(JOBS):
        if len(JOBS) + required <= MAX_JOBS:
            return
        if JOBS[key]['state'] in {'done', 'error'}:
            JOBS.pop(key)

@app.post('/api/batches')
def create_batch(payload: BatchRequest):
    """One batch = N immutable tasks, processed sequentially into a single folder."""
    validate_settings(payload.format, payload.quality, payload.authorized)
    verify_engine()
    ensure_capacity()
    if CLOUD:
        with LOCK:
            if any(j['state'] in {'queued', 'running'} for j in JOBS.values()):
                raise HTTPException(429, 'Já existe uma fila em andamento. Aguarde sua conclusão.')
    clean_urls = []
    for idx, raw in enumerate(payload.urls, 1):
        try:
            clean_urls.append(validate_url(raw))
        except ValueError as exc:
            raise HTTPException(400, f'URL {idx}: {exc}') from exc
    batch_id = uuid.uuid4().hex
    batch_folder = 'Lote_' + time.strftime('%Y%m%d_%H%M%S') + '_' + batch_id[:6]
    ids = []
    with LOCK:
        prune_old_jobs(len(clean_urls))
        if len(JOBS) + len(clean_urls) > MAX_JOBS:
            raise HTTPException(429, 'Fila cheia. Reinicie o programa após concluir os downloads anteriores.')
        # Snapshot all options once. Editing the UI during downloads cannot change these tasks.
        for idx, url in enumerate(clean_urls, 1):
            jobid = uuid.uuid4().hex
            JOBS[jobid] = {
                'id': jobid, 'batch_id': batch_id, 'batch_index': idx,
                'batch_folder': batch_folder, 'state': 'queued', 'progress': 0.0,
                'speed': '', 'eta': '', 'message': 'Aguardando sua vez...',
                'filename': None, 'created': time.time(),
                'format': payload.format, 'quality': payload.quality, 'url': url,
            }
            ids.append(jobid)
        BATCHES[batch_id] = {
            'id': batch_id, 'ids': ids, 'folder': batch_folder,
            'format': payload.format, 'quality': payload.quality, 'created': time.time(),
        }
        # Executor has one worker => no concurrent downloads. Failures do not stop later jobs.
        for jobid in ids:
            EXECUTOR.submit(run_job, jobid)
    return {'id': batch_id, 'total': len(ids), 'folder': batch_folder,
            'format': payload.format, 'quality': payload.quality}

@app.get('/api/batches/{batch_id}')
def batch_status(batch_id: str):
    with LOCK:
        batch = BATCHES.get(batch_id)
        if not batch:
            raise HTTPException(404, 'Lote não encontrado.')
        items = []
        for jobid in batch['ids']:
            job = JOBS.get(jobid)
            if not job:
                raise HTTPException(410, 'Histórico deste lote expirou. Seus arquivos continuam salvos na pasta downloads.')
            items.append({k: job.get(k) for k in ('id', 'batch_index', 'url', 'state',
                'progress', 'speed', 'eta', 'message', 'filename', 'format', 'quality')})
        completed = sum(job['state'] in {'done', 'error'} for job in items)
        succeeded = sum(job['state'] == 'done' for job in items)
        failed = sum(job['state'] == 'error' for job in items)
        return {'id': batch_id, 'folder': batch['folder'], 'total': len(items),
                'completed': completed, 'succeeded': succeeded, 'failed': failed,
                'finished': completed == len(items), 'format': batch['format'],
                'quality': batch['quality'], 'jobs': items}

@app.get('/api/batches/{batch_id}/archive')
async def download_batch_archive(batch_id: str):
    """Bundle a finished batch into one ZIP; never accept arbitrary filesystem paths."""
    with LOCK:
        batch = BATCHES.get(batch_id)
        if batch is None:
            raise HTTPException(404, 'Lote não encontrado. Reinicie a fila se o servidor foi fechado.')
        jobs = [JOBS.get(jobid) for jobid in batch['ids']]
        if any(job is None for job in jobs):
            raise HTTPException(410, 'O histórico da fila expirou.')
        if any(job['state'] not in {'done', 'error'} for job in jobs):
            raise HTTPException(409, 'Aguarde o término da fila antes de salvar todos.')
        finished_files = [(job['batch_index'], job['filename']) for job in jobs
                          if job['state'] == 'done' and job.get('filename')]
        if not finished_files:
            raise HTTPException(409, 'Nenhum download concluído neste lote.')
        folder_name = batch['folder']
    folder = (DOWNLOADS / folder_name).resolve()
    if folder.parent != DOWNLOADS.resolve() or not folder.is_dir():
        raise HTTPException(404, 'Pasta do lote não encontrada.')
    files = []
    for _, filename in finished_files:
        path = (folder / filename).resolve()
        if path.parent != folder or not path.is_file():
            raise HTTPException(404, f'Arquivo ausente da pasta do lote: {filename}')
        files.append((path, filename))
    archive = DOWNLOADS / (folder_name + '.zip')
    if CLOUD and sum(path.stat().st_size for path, _ in files) > 550 * 1024 * 1024:
        raise HTTPException(413, 'Este lote excede 550 MB para ZIP na hospedagem gratuita. Use a versão Windows para lotes grandes.')
    def build_archive():
        temp = DOWNLOADS / (folder_name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as z:
                for path, filename in files:
                    z.write(path, arcname=filename)
            os.replace(temp, archive)
        finally:
            temp.unlink(missing_ok=True)
    try:
        await asyncio.to_thread(build_archive)
    except OSError as exc:
        raise HTTPException(507, 'Não foi possível gerar o ZIP. Confira o espaço livre no disco e as permissões da pasta.') from exc
    return FileResponse(archive, filename=archive.name, media_type='application/zip')

@app.post('/api/download')
def download(payload: DownloadRequest):
    try:
        url = validate_url(payload.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    validate_settings(payload.format, payload.quality, payload.authorized)
    verify_engine()
    ensure_capacity()
    with LOCK:
        active = sum(j['state'] in {'queued', 'running'} for j in JOBS.values())
        if active >= (1 if CLOUD else 4):
            raise HTTPException(429, 'Há muitas tarefas em andamento. Conclua algumas e tente novamente.')
        if len(JOBS) >= MAX_JOBS:
            for k in list(JOBS):
                if len(JOBS) < MAX_JOBS:
                    break
                if JOBS[k]['state'] in {'done', 'error'}:
                    JOBS.pop(k)
        if len(JOBS) >= MAX_JOBS:
            raise HTTPException(429, 'Limite de tarefas atingido. Reinicie o aplicativo.')
        jobid = uuid.uuid4().hex
        task = {'id': jobid, 'state': 'queued', 'progress': 0.0, 'speed': '', 'eta': '',
                'message': 'Na fila para processamento...', 'filename': None, 'created': time.time(),
                'format': payload.format, 'quality': payload.quality, 'url': url}
        JOBS[jobid] = task
    EXECUTOR.submit(run_job, jobid)
    return {'id': jobid, 'state': 'queued'}

def update(jobid: str, **changes):
    with LOCK:
        JOBS[jobid].update(changes)

def inspect_video(file: Path) -> dict:
    """Read file metadata locally using FFmpeg (no network, no ffprobe dependency)."""
    ff = ffmpeg_path()
    result = subprocess.run([ff, '-hide_banner', '-i', str(file)], capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=35)
    details = result.stderr + result.stdout
    match_video = re.search(r'Video:\s*([^,\s]+).*?(\d{2,5})x(\d{2,5})', details)
    if not match_video:
        raise RuntimeError('Não foi possível identificar o codec e a resolução do vídeo baixado.')
    match_audio = re.search(r'Audio:\s*([^,\s]+)', details)
    match_time = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', details)
    duration = None
    if match_time:
        h, m, sec = match_time.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(sec)
    return {'video': match_video.group(1).lower(), 'w': int(match_video.group(2)),
            'h': int(match_video.group(3)),
            'audio': match_audio.group(1).lower() if match_audio else None,
            'duration': duration}


def normalize_1080_mp4(file: Path, jobid: str) -> Path:
    """Verify 1080p; keep compatible MP4 as-is, otherwise convert with LIVE progress.

    Avoid needless 1080p full-video reencoding, the source of apparently frozen
    99%-completed tasks in v1.3. Preserves proportion and never upscales.
    """
    ff = ffmpeg_path()
    if not ff:
        raise RuntimeError('FFmpeg não encontrado para finalizar MP4.')
    meta = inspect_video(file)
    w, h = meta['w'], meta['h']
    if (w >= h and h != 1080) or (w < h and w != 1080):
        raise RuntimeError(f'Arquivo veio em {w}x{h}, e não em 1080p. Mantido sem alterar o original.')
    # Ready-to-play H.264/AAC MP4: copying directly avoids a potentially hours-long transcode.
    if meta['video'] == 'h264' and meta['audio'] in {'aac', None}:
        update(jobid, progress=99.7, message='MP4 1080p H.264 verificado. Finalizando...')
        return file
    target = file.with_name(file.stem + '.convertendo.mp4')
    # If video is H264, COPY it and transcode only the audio. Otherwise encode video.
    copy_video = meta['video'] == 'h264'
    cmd = [ff, '-hide_banner', '-nostdin', '-y', '-loglevel', 'error',
           '-stats_period', '0.5', '-progress', 'pipe:1', '-i', str(file),
           '-map', '0:v:0', '-map', '0:a:0?']
    if copy_video:
        cmd += ['-c:v', 'copy']
    else:
        cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-pix_fmt', 'yuv420p']
    cmd += ['-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(target)]
    update(jobid, message=('Ajustando áudio e contêiner MP4...' if copy_video else
                           'Convertendo vídeo para MP4 H.264 (pode demorar)...'),
           progress=96.0, speed='', eta='')
    # Read output on a separate thread so a stalled FFmpeg can be terminated.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding='utf-8', errors='replace', bufsize=1)
    lines = queue.Queue()
    errors = []
    def reader():
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line.strip())
        lines.put(None)
    def read_errors():
        assert proc.stderr is not None
        for line in proc.stderr:
            errors.append(line.strip())
            if len(errors) > 20:
                errors.pop(0)
    t1 = threading.Thread(target=reader, daemon=True)
    t2 = threading.Thread(target=read_errors, daemon=True)
    t1.start(); t2.start()
    last_activity = time.monotonic()
    last_progress = 96.0
    try:
        while True:
            try:
                line = lines.get(timeout=2)
            except queue.Empty:
                if proc.poll() is not None and not t1.is_alive():
                    break
                if time.monotonic() - last_activity > 240:
                    proc.kill()
                    raise RuntimeError('FFmpeg ficou 4 minutos sem atualizar o progresso e foi interrompido. O vídeo original foi mantido.')
                continue
            if line is None:
                break
            last_activity = time.monotonic()
            if line.startswith(('out_time_us=', 'out_time_ms=')):
                try:
                    seconds = int(line.split('=', 1)[1]) / 1_000_000
                    if meta['duration'] and meta['duration'] > 0:
                        value = min(99.5, 96 + 3.5 * seconds / meta['duration'])
                        if value > last_progress:
                            last_progress = value
                            update(jobid, progress=round(value, 2),
                                   message=f'Finalizando MP4 1080p: {min(100, 100*seconds/meta["duration"]):.0f}% da conversão')
                except (ValueError, OverflowError):
                    pass
        code = proc.wait(timeout=30)
        t2.join(timeout=2)
        if code != 0 or not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError('Falha na conversão FFmpeg: ' + safe_error('\n'.join(errors)))
        converted = inspect_video(target)
        if converted['video'] != 'h264' or converted['audio'] not in {'aac', None}:
            raise RuntimeError('A conversão não produziu codecs H.264/AAC.')
        w2, h2 = converted['w'], converted['h']
        if (w2 >= h2 and h2 != 1080) or (w2 < h2 and w2 != 1080):
            raise RuntimeError(f'A conversão não preservou 1080p: {w2}x{h2}.')
        target.replace(file)
        update(jobid, progress=99.8, message='MP4 1080p verificado. Gravando arquivo...')
        return file
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        if target.exists():
            target.unlink()


def run_job(jobid: str):
    with LOCK:
        task = JOBS[jobid].copy()
    folder = DOWNLOADS / task.get('batch_folder', jobid)
    folder.mkdir(exist_ok=True)
    if CLOUD:
        try:
            ensure_capacity()
        except HTTPException as exc:
            update(jobid, state='error', message=str(exc.detail))
            return
    cmd = base_cmd() + ['--no-overwrites', '--max-filesize', str(MAX_FILE_MB) + 'M',
                        '--concurrent-fragments', '4',
                        '--progress-template', 'download:DL_PROGRESS|%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s',
                        '-o', str(folder / ((f"{task['batch_index']:03d} - " if task.get('batch_index') else '') + '%(title).90B [%(id)s].%(ext)s'))]
    if task['format'] == 'mp3':
        cmd += ['-f', 'bestaudio/best', '-x', '--audio-format', 'mp3', '--audio-quality', '2']
    else:
        q = str(task['quality'])
        if task['quality'] == 1080:
            # Require a true 1080-line video stream. Never silently substitute
            # 1440p/2160p or a lower-resolution fallback.
            # Prefer pre-encoded AVC/H.264 + AAC, avoiding expensive 1080p re-encoding.
            # If the source lacks AVC 1080p, keep the existing full-HD fallback.
            video_format = ('bv[height=1080][ext=mp4][vcodec^=avc1]+ba[ext=m4a]/'
                            'bv[height=1080][vcodec^=avc1]+ba[acodec^=mp4a]/'
                            'bv[height=1080][ext=mp4]+ba[ext=m4a]/'
                            'bv[height=1080]+ba/'
                            'b[height=1080][ext=mp4]/b[height=1080]')
        else:
            video_format = (f'bv[height<={q}][ext=mp4]+ba[ext=m4a]/'
                            f'bv[height<={q}]+ba/b[height<={q}][ext=mp4]/b[height<={q}]')
        cmd += ['-f', video_format, '--merge-output-format', 'mp4']
    cmd.append(task['url'])
    update(jobid, state='running', message='Preparando download rápido (até 4 fragmentos simultâneos)...')
    recent: list[str] = []
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding='utf-8', errors='replace', bufsize=1)
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            recent.append(line)
            recent = recent[-14:]
            if line.startswith('DL_PROGRESS|'):
                parts = line.split('|', 3)
                if len(parts) == 4:
                    number = re.search(r'(\d+(?:\.\d+)?)', parts[1])
                    if number:
                        update(jobid, progress=min(float(number.group(1)), 99.0), speed=parts[2].strip(), eta=parts[3].strip(), message='Baixando arquivo...')
            elif '[Merger]' in line or '[ExtractAudio]' in line or '[VideoConvertor]' in line:
                update(jobid, message='Convertendo/organizando mídia...', progress=99.0)
        code = proc.wait()
        if code:
            detail = safe_error('\n'.join(recent))
            if task['format'] == 'mp4' and task['quality'] == 1080 and any(
                indicator in detail.lower() for indicator in ('requested format is not available', 'requested format not available')
            ):
                raise RuntimeError('Este vídeo não oferece 1080p. Selecione 720p ou utilize um vídeo com Full HD disponível.')
            raise RuntimeError(detail)
        ext = '.mp3' if task['format'] == 'mp3' else '.mp4'
        finished = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() == ext]
        if not finished:
            raise RuntimeError('O processador terminou, mas não entregou um arquivo no formato esperado. Confira a fonte e o formato.')
        file = max(finished, key=lambda x: x.stat().st_mtime)
        if task['format'] == 'mp4' and task['quality'] == 1080:
            file = normalize_1080_mp4(file, jobid)
        update(jobid, state='done', progress=100.0, message='Arquivo pronto!', filename=file.name)
    except Exception as exc:
        update(jobid, state='error', message=str(exc)[:420], speed='', eta='')

@app.get('/api/jobs/{jobid}')
def job_status(jobid: str):
    with LOCK:
        job = JOBS.get(jobid)
        if job is None:
            raise HTTPException(404, 'Tarefa não encontrada.')
        return {k: job[k] for k in ['id', 'state', 'progress', 'speed', 'eta', 'message', 'filename', 'format', 'quality']}

@app.get('/api/files/{jobid}')
def get_file(jobid: str):
    with LOCK:
        job = JOBS.get(jobid)
        if not job or job['state'] != 'done' or not job.get('filename'):
            raise HTTPException(404, 'Arquivo não encontrado.')
        filename = job['filename']
    path = DOWNLOADS / job.get('batch_folder', jobid) / filename
    if not path.is_file():
        raise HTTPException(404, 'Arquivo removido do disco.')
    return FileResponse(path, filename=filename, media_type='application/octet-stream')

if __name__ == '__main__':
    if os.environ.get('MEDIA_NO_BROWSER') != '1':
        import threading as _threading
        _threading.Timer(2.0, lambda: webbrowser.open('http://127.0.0.1:8765')).start()
    print('\nMediaDownloader Local v' + VERSION)
    print('Interface: http://127.0.0.1:8765')
    print('Para encerrar: Ctrl+C\n')
    uvicorn.run(app, host='127.0.0.1', port=8765, log_level='warning')
