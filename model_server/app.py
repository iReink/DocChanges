from fastapi import FastAPI,HTTPException
from pydantic import BaseModel,Field
from shared import VERSION
from shared.settings import INSTALLATION_ID
from .engine import engine

app=FastAPI(title='Атлас — локальные модели',version=VERSION)

class Fragment(BaseModel):
    id:str=Field(max_length=150)
    text:str=Field(max_length=200000)

class Request(BaseModel):
    fragments:list[Fragment]=Field(min_length=1,max_length=1000)

@app.get('/health')
def health():return {'service':'atlas-models','version':VERSION,'ready':True,'installation':INSTALLATION_ID}

@app.get('/api/v1/models/status')
def status():return engine.status()

def execute(kind,request):
    try:return engine.execute(kind,[f.model_dump() for f in request.fragments])
    except Exception as exc:raise HTTPException(503,'Модель недоступна: '+type(exc).__name__+'. Проверьте журнал и установку моделей.')

@app.post('/api/v1/embeddings')
def embeddings(request:Request):return execute('embedding',request)

@app.post('/api/v1/entities')
def entities(request:Request):return execute('entities',request)
