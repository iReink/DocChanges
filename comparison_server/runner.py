import json
import sys
import traceback
from pathlib import Path
from .pipeline import run

def write_stage(folder,stage):
    (folder/'stage.txt').write_text(stage,encoding='utf-8')

def main():
    folder=Path(sys.argv[1]);meta=json.loads((folder/'meta.json').read_text(encoding='utf-8'))
    def progress(stage):
        # Windows can reject rename while the manager briefly reads stage.txt.
        # A stage is advisory; an empty concurrent read keeps the previous stage.
        write_stage(folder,stage)
    try:
        run(folder,meta,progress)
    except Exception as exc:
        diagnostic={'type':type(exc).__name__,'frames':[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(exc.__traceback__)]}
        (folder/'diagnostic.json').write_text(json.dumps(diagnostic),encoding='utf-8')
        message=str(exc) if isinstance(exc,ValueError) else 'Ошибка обработки документа. Проверьте формат и содержимое файла.'
        (folder/'error.txt').write_text(message,encoding='utf-8');sys.exit(1)

if __name__=='__main__':main()
