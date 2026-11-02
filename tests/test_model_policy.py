import pytest
from model_server.engine import Engine

def test_oom_retries_cpu(monkeypatch):
    pytest.importorskip('torch')
    engine=Engine();devices=[]
    def load(kind,force_cpu=False):
        engine.device='cpu' if force_cpu else 'cuda';devices.append(engine.device)
    def embed(items):
        if engine.device=='cuda':raise RuntimeError('CUDA out of memory')
        return [{'id':'a','vector':[1.,0.]}]
    monkeypatch.setattr(engine,'load',load);monkeypatch.setattr(engine,'_embedding',embed)
    result=engine.execute('embedding',[{'id':'a','text':'test'}])
    assert devices==['cuda','cpu'] and result['device']=='cpu' and engine.current is None

def test_gliner_offsets_and_long_suffix(monkeypatch):
    engine=Engine()
    class Tokenizer:
        def encode(self,text,**kwargs):return list(text)
    class Model:
        class Processor:transformer_tokenizer=Tokenizer()
        data_processor=Processor()
        def predict_entities(self,text,labels,**kwargs):
            start=text.find('ООО Тест')
            return [] if start<0 else [{'start':start,'end':start+8,'text':'ООО Тест','label':'organization','score':.9}]
    engine.model=Model()
    text='x'*3000+' ООО Тест'
    result=engine._entities([{'id':'long','text':text}])[0]
    assert result['entities'] and all(text[e['start']:e['end']]==e['text'] for e in result['entities'])
