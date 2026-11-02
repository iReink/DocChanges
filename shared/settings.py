"""All mutable state is relative to the project, never the user's home."""
import json
import os
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLATION_ID=hashlib.sha256(str(ROOT).lower().encode('utf-8')).hexdigest()[:12]

def settings():
    base = json.loads((ROOT / 'config/settings.json').read_text(encoding='utf-8-sig'))
    local=ROOT/'config/settings.local.json'
    if local.is_file():base.update(json.loads(local.read_text(encoding='utf-8-sig')))
    base['models_url'] = os.getenv('ATLAS_MODELS_URL', base['models_url']).rstrip('/')
    base['device'] = os.getenv('ATLAS_DEVICE', base['device'])
    return base

def configure_offline():
    for key, value in {'HF_HOME': str(ROOT / 'models/cache'), 'HF_HUB_OFFLINE': '1',
                       'TRANSFORMERS_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
                       'DO_NOT_TRACK': '1', 'TOKENIZERS_PARALLELISM': 'false'}.items():
        os.environ[key] = value
