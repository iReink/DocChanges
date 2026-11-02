"""PDF job API: bounded single-worker inference with durable result artifacts."""
import copy
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import bleach
import pypdfium2 as pdfium
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from markdown_it import MarkdownIt

from .engine import Engine, ROOT
from .postprocess.document import postprocess_e2e_markdown

app = FastAPI(title='Xiaomi OCR · Model service', version='1.0')
engine = Engine()
STORE = ROOT / 'temp/ocr-lab'
STORE.mkdir(parents=True, exist_ok=True)
pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='xiaomi')
lock = threading.RLock()
pdf_lock = threading.Lock()  # PDFium is not thread-safe.
jobs = {}
active = None
TERMINAL = {'completed', 'failed', 'cancelled'}


def update(job_id, **values):
    with lock:
        jobs[job_id].update(values)


def snapshot(job_id):
    with lock:
        if job_id not in jobs:
            raise HTTPException(404, 'Задание не найдено (результаты на диске сохраняются после перезапуска)')
        result = copy.deepcopy(jobs[job_id])
    result['elapsed_seconds'] = round((result.get('finished_at') or time.time()) - result['started_at'], 2)
    return result


def cancelled(job_id):
    with lock:
        return jobs[job_id]['cancel_requested']


def run(job_id, path, dpi, max_tokens):
    global active
    try:
        update(job_id, status='loading', stage='Загрузка модели')
        engine.load()
        update(job_id, device=engine.device, model_load_seconds=engine.load_seconds)
        total = snapshot(job_id)['total_pages']
        for index in range(total):
            if cancelled(job_id):
                break
            update(job_id, status='running', stage=f'Распознавание страницы {index + 1} из {total}', current_page=index + 1)
            started = time.perf_counter()
            with pdf_lock:
                with pdfium.PdfDocument(path) as doc:
                    page = doc[index]
                    # Protect against giant page dimensions at a valid DPI.
                    scale = min(dpi / 72, 2400 / max(page.get_size()))
                    bitmap = page.render(scale=scale)
                    image = bitmap.to_pil().convert('RGB')
                    bitmap.close()
                    page.close()
            try:
                raw, tokens, truncated = engine.recognize(image, max_tokens, lambda: cancelled(job_id))
            finally:
                image.close()
            if cancelled(job_id):
                break
            markdown = postprocess_e2e_markdown(raw, convert_otsl=True).strip()
            page_result = dict(page=index + 1, markdown=markdown, raw=raw, tokens=tokens,
                               truncated=truncated, seconds=round(time.perf_counter() - started, 3))
            with lock:
                jobs[job_id]['pages'].append(page_result)
                jobs[job_id]['completed_pages'] = index + 1
            persist(job_id)
        stopped = cancelled(job_id)
        update(job_id, status='cancelled' if stopped else 'completed',
               stage='Остановлено' if stopped else 'Распознавание завершено', finished_at=time.time())
    except Exception as exc:
        logging.exception('OCR job %s failed', job_id)
        error = str(exc)
        if 'out of memory' in error.lower():
            error = 'Недостаточно памяти GPU. Освободите VRAM или перезапустите с XIAOMI_DEVICE=cpu. ' + error
        update(job_id, status='failed', stage='Ошибка распознавания', error=error, finished_at=time.time())
    finally:
        try:
            persist(job_id)
        finally:
            with lock:
                active = None


def combined(job):
    return '\n\n---\n\n'.join(f'<!-- Страница {p["page"]} -->\n\n{p["markdown"]}' for p in job['pages'])


def persist(job_id):
    job = snapshot(job_id)
    folder = STORE / job_id
    folder.mkdir(exist_ok=True)
    (folder / 'result.json').write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder / 'result.md').write_text(combined(job), encoding='utf-8')


@app.get('/health')
def health():
    return dict(service='xiaomi-ocr', model='Xiaomi-OCR-0', model_loaded=engine.model is not None,
                device=engine.device, busy=active is not None)


@app.post('/jobs', status_code=202)
async def create(file: UploadFile = File(...), dpi: int = Form(144), max_tokens: int = Form(4096)):
    global active
    if dpi not in (96, 144, 192) or not 256 <= max_tokens <= 8192:
        raise HTTPException(422, 'DPI: 96, 144 или 192; max_tokens: 256–8192')
    with lock:
        if active is not None:
            raise HTTPException(409, 'Модель занята другим заданием')
        job_id = uuid.uuid4().hex
        active = job_id
    folder = STORE / job_id
    folder.mkdir()
    path = folder / 'input.pdf'
    try:
        size = 0
        with path.open('wb') as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 50 * 1024 * 1024:
                    raise HTTPException(413, 'Максимальный размер PDF — 50 МБ')
                out.write(chunk)
        with path.open('rb') as inp:
            if b'%PDF-' not in inp.read(1024):
                raise HTTPException(422, 'Загрузите корректный PDF-файл')
        try:
            with pdf_lock, pdfium.PdfDocument(path) as doc:
                total = len(doc)
                if total < 1 or total > 100:
                    raise HTTPException(422, 'Допустимо от 1 до 100 страниц')
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, 'PDF повреждён или защищён паролем')
        with lock:
            # Keep bounded in-memory history; artifacts remain on disk.
            if len(jobs) >= 20:
                del jobs[next(iter(jobs))]
            jobs[job_id] = dict(id=job_id, filename=Path(file.filename or 'document.pdf').name,
                status='queued', stage='Подготовка', total_pages=total, completed_pages=0,
                current_page=0, pages=[], error=None, started_at=time.time(), cancel_requested=False,
                dpi=dpi, max_tokens=max_tokens, device=None, model_load_seconds=None)
        pool.submit(run, job_id, path, dpi, max_tokens)
        return snapshot(job_id)
    except Exception:
        with lock:
            active = None
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.get('/jobs/{job_id}')
def get_job(job_id: str):
    return snapshot(job_id)


@app.post('/jobs/{job_id}/cancel')
def cancel(job_id: str):
    job = snapshot(job_id)
    if job['status'] not in TERMINAL:
        update(job_id, cancel_requested=True, stage='Остановка…')
    return snapshot(job_id)


@app.get('/jobs/{job_id}/result')
def result(job_id: str, format: str = 'md'):
    job = snapshot(job_id)
    if format == 'json':
        return Response(json.dumps(job, ensure_ascii=False, indent=2), media_type='application/json',
                        headers={'Content-Disposition': 'attachment; filename="result.json"'})
    if format == 'html':
        html = MarkdownIt('commonmark', {'html': True}).enable('table').render(combined(job))
        html = bleach.clean(html, tags=list(bleach.sanitizer.ALLOWED_TAGS) + [
            'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'hr', 'br', 'table',
            'thead', 'tbody', 'tr', 'td', 'th', 'del'], attributes={'td': ['rowspan', 'colspan'],
            'th': ['rowspan', 'colspan'], 'a': ['href', 'title']}, strip=True)
        return Response(html, media_type='text/html')
    if format != 'md':
        raise HTTPException(422, 'Формат: md, json или html')
    return Response(combined(job), media_type='text/markdown',
                    headers={'Content-Disposition': 'attachment; filename="result.md"'})
