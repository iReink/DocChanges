import argparse, importlib, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shared.settings import ROOT,settings

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--component',default='comparison');parser.add_argument('--quick',action='store_true');args=parser.parse_args()
    print('Python:',sys.version.split()[0],flush=True)
    imports=['fastapi','uvicorn']
    if args.component=='models':imports+=['torch','gliner','sentence_transformers']
    elif args.component=='comparison':imports+=['docx','pdfplumber','pypdfium2','pyhanko']
    for name in imports:importlib.import_module(name)
    print('Библиотеки: готовы.',flush=True)
    if args.component=='models':
        import torch
        print('CUDA:',torch.cuda.is_available(),'; режим:',settings()['device'],flush=True)
        print('Бюджет VRAM:',settings()['vram_budget_mb'],'МБ',flush=True)
    if args.component=='comparison':
        from comparison_server.extract import soffice_path,convert
        print('Конвертер:',soffice_path() or 'НЕ УСТАНОВЛЕН',flush=True)
        if soffice_path() and not args.quick:
            from docx import Document
            with tempfile.TemporaryDirectory(dir=ROOT/'runtime') as folder:
                path=Path(folder)/'probe.docx';doc=Document();doc.add_paragraph('Проверка преобразования документа');doc.save(path)
                pdf=convert(path,'pdf:writer_pdf_Export',Path(folder)/'pdf')
                print('Пробное преобразование:',pdf.is_file(),flush=True)
        elif not soffice_path() and not args.quick:raise RuntimeError('Запустите start_comparison.bat для установки конвертера.')
        elif args.quick:print('Прогрев и проверка конвертера выполняются при запуске сервера.',flush=True)
    if not args.quick:
        import httpx
        for name,port in [('web',settings()['web_port']),('comparison',settings()['comparison_port']),('models',settings()['models_port'])]:
            try:print(name,httpx.get(f'http://127.0.0.1:{port}/health',timeout=2,trust_env=False).json())
            except Exception:print(name,': не запущен')

if __name__=='__main__':main()
