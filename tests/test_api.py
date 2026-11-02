import io,json,time,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from comparison_server.app import app,jobs
import pytest

@pytest.fixture(autouse=True)
def isolated_tasks(tmp_path,monkeypatch):
    # Lifecycle tests must not depend on a developer's running GPU/model server.
    monkeypatch.setenv('ATLAS_MODELS_URL','http://127.0.0.1:1')
    path=tmp_path/'tasks';path.mkdir()
    monkeypatch.setattr(jobs,'root',path)
    from comparison_server.converter import converter
    monkeypatch.setattr(converter,'start',lambda:None)
    monkeypatch.setattr(converter,'close',lambda:None)

def pdf(text):
    stream=io.BytesIO();c=canvas.Canvas(stream);c.drawString(60,760,text);c.save();return stream.getvalue()

def wait(client,jid):
    for _ in range(100):
        state=client.get('/api/v1/comparisons/'+jid).json()
        if state['state'] not in ('queued','running'):return state
        time.sleep(.15)
    raise AssertionError('Task timed out')

def test_api_lifecycle_and_reports():
    with TestClient(app) as client:
        response=client.post('/api/v1/comparisons',data={'employee':'Тестовый сотрудник'},files={'old':('old.pdf',pdf('Amount 100 USD'),'application/pdf'),'new':('new.pdf',pdf('Amount 200 USD'),'application/pdf')})
        assert response.status_code==202,response.text
        jid=response.json()['id'];state=wait(client,jid)
        assert state['state']=='completed',state
        result=client.get(f'/api/v1/comparisons/{jid}/result').json()
        assert result['count']>=1 and result['partial']
        assert client.get(f'/api/v1/comparisons/{jid}/documents/old/preview').content.startswith(b'%PDF')
        for fmt in ('pdf','docx','json'):
            r=client.get(f'/api/v1/comparisons/{jid}/reports/{fmt}');assert r.status_code==200 and len(r.content)>100
        assert client.post(f'/api/v1/comparisons/{jid}/heartbeat').status_code==200
        assert client.delete(f'/api/v1/comparisons/{jid}').status_code==200
        assert client.get(f'/api/v1/comparisons/{jid}/result').status_code==404

def test_invalid_files_and_unknown():
    with TestClient(app) as client:
        assert client.get('/api/v1/comparisons/'+str(uuid.uuid4())).status_code==404
        assert client.post('/api/v1/comparisons',data={'employee':'x'},files={'old':('x.exe',b'bad'),'new':('y.pdf',pdf('text'))}).status_code==422
        response=client.post('/api/v1/comparisons',data={'employee':'x'},files={'old':('x.pdf',b'not pdf'),'new':('y.pdf',pdf('text'))})
        state=wait(client,response.json()['id']);assert state['state']=='failed' and 'PDF' in state['error']


def test_provisional_result_and_preview_before_classification(tmp_path,monkeypatch):
    jid=str(uuid.uuid4());folder=jobs.root/jid;folder.mkdir();(folder/'old').mkdir()
    data={'id':jid,'provisional':True,'revision':1,'count':2,'changes':[]}
    (folder/'snapshot-1.json').write_text(json.dumps(data),encoding='utf8')
    (folder/'old/preview.pdf').write_bytes(pdf('Early result'))
    monkeypatch.setattr(jobs,'start',lambda:None)
    monkeypatch.setattr(jobs,'close',lambda:None)
    monkeypatch.setattr(jobs,'get',lambda *a,**k:{'id':jid,'state':'running','stage':'Классификация'})
    with TestClient(app) as client:
        state=client.get(f'/api/v1/comparisons/{jid}').json()
        assert state['result_available'] and not state['ready'] and state['result_revision']==1
        assert client.get(f'/api/v1/comparisons/{jid}/result').json()==data
        assert client.get(f'/api/v1/comparisons/{jid}/documents/old/preview').status_code==200
        assert client.get(f'/api/v1/comparisons/{jid}/reports/pdf').status_code==409
