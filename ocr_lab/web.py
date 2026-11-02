"""UI gateway. XIAOMI_API_URL can point at a separate model machine."""
import os
from pathlib import Path
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

app = FastAPI(title='Xiaomi OCR · UI gateway')
API = os.getenv('XIAOMI_API_URL', 'http://127.0.0.1:8021').rstrip('/')


@app.api_route('/api/{path:path}', methods=['GET', 'POST'])
async def proxy(path: str, request: Request):
    if path != 'health' and path != 'jobs' and not path.startswith('jobs/'):
        return JSONResponse({'detail': 'Unknown endpoint'}, status_code=404)
    # Bound upload memory at the gateway as well as the model service.
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 51 * 1024 * 1024:
            return JSONResponse({'detail': 'Максимальный размер PDF — 50 МБ'}, status_code=413)
        chunks.append(chunk)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.request(
                request.method, f'{API}/{path}', params=request.query_params,
                content=b''.join(chunks), headers={'content-type': request.headers.get('content-type', '')})
        headers = {'content-type': response.headers.get('content-type', 'application/json')}
        if 'content-disposition' in response.headers:
            headers['content-disposition'] = response.headers['content-disposition']
        return Response(response.content, response.status_code, headers=headers)
    except httpx.HTTPError:
        return JSONResponse({'detail': 'Сервер модели недоступен. Запустите start_ocr.bat.'}, status_code=503)


app.mount('/pdfjs', StaticFiles(directory=Path(__file__).resolve().parents[1] / 'vendor/pdfjs'), name='pdfjs')
app.mount('/', StaticFiles(directory=Path(__file__).parent / 'static', html=True), name='ui')
