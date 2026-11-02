"""Relocated real copy on the same Windows PC; no preinstalled Python in the copy."""
import json,os,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    target=ROOT/'work/Копия проекта с пробелами'
    target.mkdir(parents=True,exist_ok=True)
    def copy(source,dest):
        source,dest=Path(source),Path(dest)
        if dest.is_file() and source.stat().st_size==dest.stat().st_size and source.stat().st_mtime_ns==dest.stat().st_mtime_ns:return str(dest)
        return shutil.copy2(source,dest)
    for name in ('web','comparison_server','model_server','shared','config','scripts','vendor'):
        print('Копирование '+name,flush=True)
        shutil.copytree(ROOT/name,target/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'),copy_function=copy)
    for pattern in ('requirements-*','*.bat','README_RU.md'):
        for path in ROOT.glob(pattern):shutil.copy2(path,target/path.name)
    for name in ('python','tools'):
        shutil.copytree(ROOT/'runtime'/name,target/'runtime'/name,dirs_exist_ok=True,copy_function=copy)
    for spec in json.loads((ROOT/'config/models.json').read_text()).values():
        print('Копирование модели '+spec['folder'],flush=True)
        shutil.copytree(ROOT/'models'/spec['folder'],target/'models'/spec['folder'],dirs_exist_ok=True,copy_function=copy,
                        ignore=shutil.ignore_patterns('.cache'))
        if 'backbone' in spec:
            name=spec['backbone']['folder'];shutil.copytree(ROOT/'models'/name,target/'models'/name,dirs_exist_ok=True,copy_function=copy)
    (target/'runtime/downloads').mkdir(parents=True,exist_ok=True)
    for path in (ROOT/'runtime/downloads').glob('*.paf.exe'):copy(path,target/'runtime/downloads'/path.name)
    cfg=json.loads((target/'config/settings.json').read_text());cfg.update(web_port=18080,comparison_port=18000,models_port=18001,models_url='http://127.0.0.1:18001',device='cpu')
    (target/'config/settings.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    env=os.environ.copy();env.update(ATLAS_NO_BROWSER='1',ATLAS_DEVICE='cpu',PYTHONUTF8='1');env.pop('ATLAS_PREPARE_ONLY',None)
    cmd=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(target/'scripts/bootstrap.ps1')]
    try:
        subprocess.run(cmd+['-Mode','all'],cwd=target,env=env,check=True)
        import httpx
        with httpx.Client(timeout=5,trust_env=False) as client:
            services=[client.get(f'http://127.0.0.1:{p}/health').json() for p in (18080,18000,18001)]
            assert len({s['installation'] for s in services})==1
        (ROOT/'work/portability-check.json').write_text(json.dumps({'root':str(target),'services':services,'result':'passed','separate_pc':False},ensure_ascii=False,indent=2),encoding='utf-8')
        print('Перенесённая копия: все три приложения запущены.',flush=True)
    finally:subprocess.run(cmd+['-Mode','stop'],cwd=target,env=env)

if __name__=='__main__':main()
