import json
from shared import settings as module


def test_local_configuration_overrides_defaults_without_editing_public_file(tmp_path,monkeypatch):
    config=tmp_path/'config';config.mkdir()
    base={'models_url':'http://127.0.0.1:8001','device':'auto','api_url':'','host':'0.0.0.0'}
    (config/'settings.json').write_text(json.dumps(base),encoding='utf-8')
    (config/'settings.local.json').write_text(json.dumps({'models_url':'http://192.168.1.30:8001','api_url':'http://192.168.1.20:8000'}),encoding='utf-8-sig')
    monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.delenv('ATLAS_MODELS_URL',raising=False);monkeypatch.delenv('ATLAS_DEVICE',raising=False)
    value=module.settings()
    assert value['models_url']=='http://192.168.1.30:8001' and value['host']=='0.0.0.0'
    assert json.loads((config/'settings.json').read_text())==base
