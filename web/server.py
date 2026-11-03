from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from shared import VERSION
from shared.settings import ROOT,settings,INSTALLATION_ID

def create_proxy_client():
    # LAN requests must not inherit a workstation's corporate HTTP proxy.
    return httpx.AsyncClient(timeout=httpx.Timeout(180, connect=10),
                             follow_redirects=False, trust_env=False)


@asynccontextmanager
async def lifespan(app):
    async with create_proxy_client() as client:
        app.state.proxy_client = client
        yield


app=FastAPI(title='Атлас — веб-интерфейс', lifespan=lifespan)


def upstream_url():
    cfg = settings()
    return (cfg['api_url'] or f"http://127.0.0.1:{cfg['comparison_port']}").rstrip('/')


def proxy_headers(headers):
    # Remove hop-by-hop headers, including names declared by Connection.
    blocked = {'host', 'connection', 'keep-alive', 'proxy-authenticate',
               'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade'}
    blocked.update(x.strip().lower() for x in headers.get('connection', '').split(','))
    return [(k, v) for k, v in headers.raw if k.decode('latin1').lower() not in blocked]


@app.api_route('/comparison-api/{path:path}', methods=['GET', 'HEAD', 'POST', 'DELETE', 'OPTIONS'])
async def comparison_proxy(path: str, request: Request):
    # The destination comes only from administrator configuration, never a URL
    # supplied by the browser. Do not turn this into a general-purpose proxy.
    if (path != 'health' and not path.startswith('api/v1/')) or any(
        part in {'.', '..'} for part in path.split('/')
    ) or '\\' in path:
        return JSONResponse({'detail': 'Неизвестный путь API.'}, status_code=404)
    target = httpx.URL(upstream_url() + '/' + path).copy_with(query=request.url.query.encode('ascii') or None)
    client = request.app.state.proxy_client
    upstream_request = client.build_request(request.method, target,
        headers=proxy_headers(request.headers), content=request.stream())
    try:
        response = await client.send(upstream_request, stream=True)
    except httpx.TimeoutException:
        return JSONResponse({'detail': 'Сервер сравнения не ответил вовремя. Повторите запрос.'}, status_code=504)
    except httpx.RequestError:
        return JSONResponse({'detail': 'Веб-интерфейс не может подключиться к серверу сравнения. '
            'Запустите start_comparison.bat или проверьте адрес через configure.bat.'}, status_code=502)

    async def body():
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()

    result = StreamingResponse(body(), status_code=response.status_code)
    result.raw_headers = proxy_headers(response.headers)
    return result

@app.get('/health')
def health():return {'service':'atlas-web','version':VERSION,'ready':True,'installation':INSTALLATION_ID}

@app.get('/config.json')
def config():return {'api_url':'/comparison-api','comparison_port':settings()['comparison_port']}

app.mount('/vendor',StaticFiles(directory=ROOT/'vendor'),name='vendor')
app.mount('/',StaticFiles(directory=ROOT/'web/static',html=True),name='web')
