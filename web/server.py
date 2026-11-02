from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from shared import VERSION
from shared.settings import ROOT,settings,INSTALLATION_ID

app=FastAPI(title='Атлас — веб-интерфейс')

@app.get('/health')
def health():return {'service':'atlas-web','version':VERSION,'ready':True,'installation':INSTALLATION_ID}

@app.get('/config.json')
def config():return {'api_url':settings()['api_url'],'comparison_port':settings()['comparison_port']}

app.mount('/vendor',StaticFiles(directory=ROOT/'vendor'),name='vendor')
app.mount('/',StaticFiles(directory=ROOT/'web/static',html=True),name='web')
