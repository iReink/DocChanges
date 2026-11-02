"""Contract and lifecycle tests use a fake engine; real inference is a separate smoke check."""
import threading
import time
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ocr_lab import api


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, 'STORE', tmp_path)
    with TestClient(api.app) as client:
        yield client
    for _ in range(100):
        if api.active is None:
            break
        time.sleep(.02)


def pdf_bytes(tmp_path):
    # Image-only PDF proves this path does not depend on embedded PDF text.
    path = tmp_path / 'scan.pdf'
    Image.new('RGB', (300, 400), 'white').save(path, 'PDF')
    return path.read_bytes()


def wait(client, job_id):
    for _ in range(100):
        job = client.get(f'/jobs/{job_id}').json()
        if job['status'] in api.TERMINAL:
            return job
        time.sleep(.02)
    pytest.fail('job did not finish')


def test_pdf_contract_artifacts_and_safe_html(client, tmp_path, monkeypatch):
    monkeypatch.setattr(api.engine, 'load', lambda: None)
    monkeypatch.setattr(api.engine, 'recognize', lambda *args: (
        '# Hello\n\n<script>alert(1)</script>\n\n<fcel>A<fcel>B<nl><fcel>1<fcel>2<nl>', 42, False))
    r = client.post('/jobs', files={'file': ('scan.pdf', pdf_bytes(tmp_path), 'application/pdf')})
    assert r.status_code == 202
    job = wait(client, r.json()['id'])
    assert job['status'] == 'completed' and job['completed_pages'] == 1
    assert '<table>' in job['pages'][0]['markdown']
    assert (tmp_path / job['id'] / 'result.json').exists()
    assert '# Hello' in client.get(f'/jobs/{job["id"]}/result').text
    html = client.get(f'/jobs/{job["id"]}/result?format=html').text
    assert '<script' not in html and '<table>' in html
    assert client.get(f'/jobs/{job["id"]}/result?format=json').json()['pages'][0]['tokens'] == 42


def test_reject_bad_pdf_and_settings(client):
    assert client.post('/jobs', files={'file': ('bad.pdf', b'not a pdf')}).status_code == 422
    assert api.active is None
    assert client.post('/jobs', data={'dpi': 100}, files={'file': ('bad.pdf', b'%PDF-1.4')}).status_code == 422
    assert client.get('/jobs/missing').status_code == 404


def test_busy_cancel_and_recovery(client, tmp_path, monkeypatch):
    entered = threading.Event()
    def recognize(image, tokens, cancelled):
        entered.set()
        for _ in range(200):
            if cancelled():
                return 'partial', 1, False
            time.sleep(.01)
        raise RuntimeError('test timed out')
    monkeypatch.setattr(api.engine, 'load', lambda: None)
    monkeypatch.setattr(api.engine, 'recognize', recognize)
    data = pdf_bytes(tmp_path)
    job_id = client.post('/jobs', files={'file': ('a.pdf', data)}).json()['id']
    assert entered.wait(2)
    assert client.post('/jobs', files={'file': ('a.pdf', data)}).status_code == 409
    assert client.post(f'/jobs/{job_id}/cancel').status_code == 200
    assert wait(client, job_id)['status'] == 'cancelled'
    monkeypatch.setattr(api.engine, 'recognize', lambda *args: (_ for _ in ()).throw(RuntimeError('inference broke')))
    second = client.post('/jobs', files={'file': ('a.pdf', data)}).json()['id']
    assert wait(client, second)['status'] == 'failed'
    assert 'inference broke' in client.get(f'/jobs/{second}').json()['error']
