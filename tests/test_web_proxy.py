import httpx
import pytest
from fastapi.testclient import TestClient
from web import server


@pytest.fixture
def proxy(monkeypatch):
    seen = []

    async def handle(request):
        seen.append((request, await request.aread()))
        if request.url.path == '/health':
            return httpx.Response(200, stream=httpx.ByteStream(b'{"service":"atlas-comparison"}'),
                                  headers={'content-type': 'application/json'})
        if request.url.path.endswith('/missing'):
            return httpx.Response(404, stream=httpx.ByteStream(b'{"detail":"missing"}'))
        return httpx.Response(206 if 'range' in request.headers else 202,
            stream=httpx.ByteStream(b'%PDF-test'), headers={
                'content-type': 'application/pdf', 'content-length': '9',
                'content-disposition': 'attachment; filename="report.pdf"',
                'content-range': 'bytes 0-8/9', 'connection': 'keep-alive, x-private',
                'x-private': 'remove'})

    monkeypatch.setattr(server, 'create_proxy_client', lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(server, 'settings', lambda: {'api_url': '', 'comparison_port': 8123})
    with TestClient(server.app) as client:
        yield client, seen


def test_web_health_and_same_origin_config(proxy):
    client, seen = proxy
    assert client.get('/health').json()['service'] == 'atlas-web'
    assert client.get('/config.json').json()['api_url'] == '/comparison-api'
    assert client.get('/comparison-api/health').json()['service'] == 'atlas-comparison'
    assert str(seen[0][0].url) == 'http://127.0.0.1:8123/health'


def test_lan_destination_and_multipart_upload(proxy, monkeypatch):
    client, seen = proxy
    monkeypatch.setattr(server, 'settings', lambda: {'api_url': 'http://192.168.0.109:8000', 'comparison_port': 8000})
    response = client.post('/comparison-api/api/v1/comparisons?test=one%20two',
        data={'employee': 'Иванов'}, files={'old': ('old.pdf', b'original-bytes')})
    assert response.status_code == 202
    req, body = seen[0]
    assert str(req.url) == 'http://192.168.0.109:8000/api/v1/comparisons?test=one%20two'
    assert b'original-bytes' in body and 'Иванов'.encode() in body
    assert req.headers['content-type'].startswith('multipart/form-data; boundary=')
    assert req.headers['host'] == '192.168.0.109:8000'


def test_range_download_errors_and_delete(proxy):
    client, seen = proxy
    response = client.get('/comparison-api/api/v1/comparisons/id/documents/old/preview',
                          headers={'range': 'bytes=0-8'})
    assert response.status_code == 206 and response.content == b'%PDF-test'
    assert response.headers['content-range'] == 'bytes 0-8/9'
    assert 'attachment' in response.headers['content-disposition']
    assert 'connection' not in response.headers and 'x-private' not in response.headers
    assert seen[0][0].headers['range'] == 'bytes=0-8'
    assert client.get('/comparison-api/api/v1/missing').status_code == 404
    assert client.delete('/comparison-api/api/v1/comparisons/id').status_code == 202
    assert seen[-1][0].method == 'DELETE'
    count = len(seen)
    assert client.get('/comparison-api/config.json').status_code == 404
    assert client.get('/comparison-api/https://example.com').status_code == 404
    assert len(seen) == count


@pytest.mark.parametrize('error,status', [(httpx.ConnectError, 502), (httpx.ReadTimeout, 504)])
def test_connection_failure_is_readable(monkeypatch, error, status):
    async def fail(request):
        raise error('test', request=request)
    monkeypatch.setattr(server, 'create_proxy_client', lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(fail)))
    with TestClient(server.app) as client:
        response = client.get('/comparison-api/health')
        assert response.status_code == status
        assert 'Сервер' in response.json()['detail'] or 'сервер' in response.json()['detail']
