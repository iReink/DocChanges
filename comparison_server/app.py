import asyncio
import json
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
import httpx
from fastapi import FastAPI,File,Form,UploadFile,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from shared import VERSION
from shared.settings import ROOT,settings,INSTALLATION_ID
from .jobs import Jobs
from .extract import soffice_path
from .reports import make_report
from .converter import converter

jobs=Jobs()

@asynccontextmanager
async def lifespan(app):
    converter.start()
    try:
        jobs.start()
        yield
    finally:
        jobs.close()
        converter.close()

app=FastAPI(title='Атлас — сравнение документов',version=VERSION,lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'],allow_credentials=False)

@app.middleware('http')
async def no_cache(request,call_next):
    response=await call_next(request);response.headers['Cache-Control']='no-store';return response

@app.get('/health')
def health():return {'service':'atlas-comparison','version':VERSION,'ready':True,'installation':INSTALLATION_ID,'converter':converter.status()}

@app.get('/api/v1/capabilities')
async def capabilities():
    cfg=settings();model={'available':False}
    try:
        async with httpx.AsyncClient(timeout=2,trust_env=False) as client:
            r=await client.get(cfg['models_url']+'/api/v1/models/status');r.raise_for_status();model=dict(r.json(),available=True)
    except Exception:pass
    return {'formats':['doc','docx','pdf'],'ocr':False,'converter':bool(soffice_path()),
            'models':model,'limits':{k:cfg[k] for k in ('max_file_mb','max_pages','max_signatures','queue_size','idle_seconds')}}

async def save_upload(upload:UploadFile,path:Path):
    size=0;limit=settings()['max_file_mb']*1024*1024
    with path.open('wb') as output:
        while chunk:=await upload.read(1024*1024):
            size+=len(chunk)
            if size>limit:raise HTTPException(413,'Файл превышает допустимый размер.')
            output.write(chunk)
    if not size:raise HTTPException(422,'Получен пустой файл.')

@app.post('/api/v1/comparisons',status_code=202)
async def create(old:Annotated[UploadFile,File()],new:Annotated[UploadFile,File()],employee:Annotated[str,Form()],
                 old_signatures:list[UploadFile]=File(default=[]),new_signatures:list[UploadFile]=File(default=[])):
    if not employee.strip():raise HTTPException(422,'Укажите ФИО сотрудника.')
    if any(len(s)>settings()['max_signatures'] for s in (old_signatures,new_signatures)):
        raise HTTPException(422,'Слишком много файлов подписи.')
    jid=str(uuid.uuid4());folder=jobs.root/jid;folder.mkdir()
    meta={'id':jid,'employee':employee.strip()[:250]}
    try:
        for side,upload,sigs in [('old',old,old_signatures),('new',new,new_signatures)]:
            sub=folder/side;sub.mkdir()
            name=Path((upload.filename or '').replace('\\','/')).name
            if Path(name).suffix.lower() not in ('.doc','.docx','.pdf'):raise HTTPException(422,'Поддерживаются DOC, DOCX и PDF.')
            meta[side]={'name':name}
            await save_upload(upload,sub/'original')
            for i,sig in enumerate(sigs):await save_upload(sig,sub/f'signature-{i:02}')
        (folder/'meta.json').write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')
        jobs.add(meta)
    except Exception as exc:
        shutil.rmtree(folder,ignore_errors=True)
        if isinstance(exc,HTTPException):raise
        raise HTTPException(429 if isinstance(exc,ValueError) else 500,str(exc) if isinstance(exc,ValueError) else 'Не удалось принять файлы.')
    return {'id':jid,'state':'queued'}

def require(jid,complete=False):
    job=jobs.get(jid,touch=True)
    if not job:raise HTTPException(404,'Задача удалена или не существует. Загрузите документы повторно.')
    if complete and job['state']!='completed':raise HTTPException(409,'Результат ещё не готов.')
    return job

@app.get('/api/v1/comparisons/{jid}')
def state(jid:str):
    job=require(jid);job['ready']=job['state']=='completed'
    snapshots=list((jobs.root/jid).glob('snapshot-*.json'))
    job['result_available']=job['ready'] or bool(snapshots)
    job['result_revision']=max((int(p.stem.split('-')[1]) for p in snapshots),default=0)+(1 if job['ready'] else 0)
    with jobs.lock:
        queued=[x['id'] for x in jobs.items.values() if x['state']=='queued']
    job['queue_position']=queued.index(jid)+1 if jid in queued else 0
    return job

@app.get('/api/v1/comparisons/{jid}/result')
def result(jid:str):
    job=require(jid)
    if job['state']=='completed':path=jobs.root/jid/'result.json'
    else:
        snapshots=list((jobs.root/jid).glob('snapshot-*.json'))
        if not snapshots:raise HTTPException(409,'Предварительный результат ещё не готов.')
        path=max(snapshots,key=lambda p:int(p.stem.split('-')[1]))
    return json.loads(path.read_text(encoding='utf-8'))

@app.get('/api/v1/comparisons/{jid}/documents/{side}/preview')
def preview(jid:str,side:str):
    require(jid)
    if side not in ('old','new'):raise HTTPException(404)
    if not (jobs.root/jid/side/'preview.pdf').is_file():raise HTTPException(409,'Страницы ещё не готовы.')
    return FileResponse(jobs.root/jid/side/'preview.pdf',media_type='application/pdf')

@app.get('/api/v1/comparisons/{jid}/reports/{fmt}')
async def report(jid:str,fmt:str):
    if fmt not in ('pdf','docx','json'):raise HTTPException(404)
    require(jid,True)
    data=result(jid)
    # Serialise report generation: shared font registration and duplicate exports.
    async with report_lock:
        path=await asyncio.to_thread(make_report,data,jobs.root/jid,fmt)
    media={'pdf':'application/pdf','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','json':'application/json'}
    return FileResponse(path,filename='atlas-report.'+fmt,media_type=media[fmt])

report_lock=asyncio.Lock()

@app.post('/api/v1/comparisons/{jid}/heartbeat')
def heartbeat(jid:str):require(jid);return {'ok':True,'expires_in':settings()['idle_seconds']}

@app.delete('/api/v1/comparisons/{jid}')
def delete(jid:str):
    require(jid);jobs.delete(jid);return {'state':'cancelled','deleted':True}
