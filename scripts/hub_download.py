"""Immutable HF snapshots: resumable HTTP ranges and LFS SHA-256 verification."""
import hashlib,json,ssl,urllib.request,time,shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import certifi
ROOT=Path(__file__).resolve().parents[1]
TLS=ssl.create_default_context(cafile=certifi.where())

def open_url(url,headers=None):
    return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'AtlasDemo/0.1',**(headers or {})}),context=TLS,timeout=90)

def download_file(spec,file,target):
    name=file['path'];path=target/name;path.parent.mkdir(parents=True,exist_ok=True)
    size=file['size'];sha=file.get('lfs',{}).get('oid')
    def valid():
        if not path.is_file() or path.stat().st_size!=size:return False
        if not sha:return True
        with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()==sha
    if valid():return
    url=f"https://huggingface.co/{spec['id']}/resolve/{spec['revision']}/{name}"
    print(f'{name}: {size//1048576} МБ',flush=True)
    if size>1048576:
        chunks=ROOT/'models/downloads'/spec['folder']/name.replace('/','_');chunks.mkdir(parents=True,exist_ok=True)
        partsize=4*1048576;count=(size+partsize-1)//partsize
        def piece(index):
            start=index*partsize;end=min(size-1,start+partsize-1);dest=chunks/str(index)
            if dest.exists() and dest.stat().st_size==end-start+1:return
            for attempt in range(4):
                try:
                    with open_url(url+f'?download=true&atlasPart={index}',{'Range':f'bytes={start}-{end}'}) as response:
                        if response.status!=206:raise RuntimeError('Нет поддержки частичной загрузки')
                        data=response.read()
                    if len(data)!=end-start+1:raise RuntimeError('Неполная часть файла')
                    dest.write_bytes(data);return
                except Exception:
                    if attempt==3:raise
                    time.sleep(1)
        with ThreadPoolExecutor(max_workers=32) as pool:
            for i,future in enumerate(as_completed([pool.submit(piece,i) for i in range(count)]),1):
                future.result()
                if i%8==0 or i==count:print(f'{name}: частей {i}/{count}',flush=True)
        temp=path.with_suffix(path.suffix+'.part')
        with temp.open('wb') as out:
            for i in range(count):out.write((chunks/str(i)).read_bytes())
        temp.replace(path)
    else:
        with open_url(url) as response:data=response.read()
        path.write_bytes(data)
    if not valid():raise RuntimeError('Не совпали размер или SHA-256: '+name+'. Удалите соответствующие части в models/downloads и повторите запуск.')
    if size>1048576:
        resolved=chunks.resolve();resolved.relative_to((ROOT/'models/downloads').resolve())
        shutil.rmtree(resolved)

def snapshot(spec,backbone=False):
    target=ROOT/'models'/spec['folder'];marker=target/'.complete'
    if marker.exists():
        stored=json.loads(marker.read_text())
        intact=stored.get('revision')==spec['revision'] and all((target/n).is_file() and (target/n).stat().st_size==s for n,s in stored.get('files',{}).items())
        if intact:
            for name,expected in stored.get('sha256',{}).items():
                with (target/name).open('rb') as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=expected:intact=False;break
        if intact:
            if 'backbone' in spec:snapshot(spec['backbone'],True)
            if 'sha256' not in stored:
                stored['sha256']={}
                for name in stored['files']:
                    with (target/name).open('rb') as stream:stored['sha256'][name]=hashlib.file_digest(stream,'sha256').hexdigest()
                marker.write_text(json.dumps(stored),encoding='utf-8')
            print(spec['id']+': локальные файлы готовы.',flush=True);return
    target.mkdir(parents=True,exist_ok=True)
    print('Подготовка '+spec['id']+' @ '+spec['revision'][:12],flush=True)
    with open_url(f"https://huggingface.co/api/models/{spec['id']}/tree/{spec['revision']}?recursive=true") as response:files=json.load(response)
    selected=[]
    for file in files:
        if file.get('type')!='file':continue
        name=file['path']
        if name=='unigram.json':continue
        if name.startswith(('onnx/','openvino/')):continue
        if name.endswith(('.json','.model','.txt')) or (not backbone and name=='model.safetensors'):selected.append(file)
    for file in sorted(selected,key=lambda f:f['size']):download_file(spec,file,target)
    if 'backbone' in spec:
        snapshot(spec['backbone'],True)
        config_path=target/'gliner_config.json';config=json.loads(config_path.read_text())
        config['model_name']='models/'+spec['backbone']['folder'];config_path.write_text(json.dumps(config),encoding='utf-8')
    files={str(p.relative_to(target)):p.stat().st_size for p in target.rglob('*') if p.is_file() and '.cache' not in p.parts and p.name!='.complete'}
    checksums={f['path']:f['lfs']['oid'] for f in selected if f.get('lfs')}
    marker.write_text(json.dumps({'revision':spec['revision'],'files':files,'sha256':checksums}),encoding='utf-8')
    print('Модель сохранена: '+str(target),flush=True)

def main():
    manifest=json.loads((ROOT/'config/models.json').read_text(encoding='utf-8'))
    for spec in manifest.values():snapshot(spec)

if __name__=='__main__':main()
