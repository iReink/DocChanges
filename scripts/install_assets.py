"""Pinned portable dependencies, installed only by bootstrap."""
import argparse, base64, hashlib, os, subprocess, tarfile, urllib.request,ssl,json
import certifi
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'runtime/downloads'
TLS=ssl.create_default_context(cafile=certifi.where())
ASSETS={
 'font':('https://raw.githubusercontent.com/notofonts/noto-fonts/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf','b85c38ecea8a7cfb39c24e395a4007474fa5a4fc864f6ee33309eb4948d232d5'),
 'libreoffice':('https://download.documentfoundation.org/libreoffice/portable/26.2.4/LibreOfficePortable_26.2.4_MultilingualAll.paf.exe','297dd083640ec06679dd7996a16323308bdd92e641b9171c5ba2a27c52b5d4af'),
 'pdfjs':('https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-5.4.296.tgz','DlOzet0HO7OEnmUmB6wWGJrrdvbyJKftI1bhMitK7O2N8W2gc757yyYBbINy9IDafXAV9wmKr9t7xsTaNKRG5Q==')}

def download(name):
    CACHE.mkdir(parents=True,exist_ok=True)
    url,digest=ASSETS[name];path=CACHE/Path(url).name
    def valid():
        if not path.exists():return False
        data=path.read_bytes()
        return (base64.b64encode(hashlib.sha512(data).digest()).decode()==digest if name=='pdfjs' else hashlib.sha256(data).hexdigest()==digest)
    if valid():print(f'{name}: установочный файл уже скачан.',flush=True);return path
    print(f'{name}: скачивание. Установочный файл останется в runtime/downloads.',flush=True)
    temp=path.with_suffix(path.suffix+'.part')
    if name=='libreoffice':
        # The official mirror may throttle each connection. Bounded parallel ranges
        # also retain completed chunks when installation is interrupted.
        mirror='https://ftp.fau.de/tdf/libreoffice/portable/26.2.4/'+Path(url).name
        probe=urllib.request.Request(mirror,headers={'Range':'bytes=0-0','User-Agent':'AtlasDemo/0.1'})
        try:
            with urllib.request.urlopen(probe,timeout=30,context=TLS) as response:
                total=int(response.headers['Content-Range'].split('/')[-1])
            size=4*1024*1024;chunks=CACHE/'libreoffice-chunks';chunks.mkdir(exist_ok=True)
            def fetch(index):
                start=index*size;end=min(total-1,start+size-1);piece=chunks/str(index)
                if piece.exists() and piece.stat().st_size==end-start+1:return piece
                for attempt in range(3):
                    try:
                        request=urllib.request.Request(mirror+'?atlasPart='+str(index),headers={'Range':f'bytes={start}-{end}','User-Agent':'AtlasDemo/0.1'})
                        with urllib.request.urlopen(request,timeout=90,context=TLS) as source:
                            if source.status!=206:raise RuntimeError('Mirror does not support ranges')
                            data=source.read()
                        if len(data)!=end-start+1:raise RuntimeError('Incomplete download')
                        piece.write_bytes(data);return piece
                    except Exception:
                        if attempt==2:raise
            count=(total+size-1)//size
            with ThreadPoolExecutor(max_workers=12) as pool:
                for i,future in enumerate(as_completed([pool.submit(fetch,i) for i in range(count)]),1):
                    future.result();print(f'libreoffice: части {i}/{count}',flush=True)
            with temp.open('wb') as out:
                for i in range(count):out.write((chunks/str(i)).read_bytes())
            temp.replace(path)
            if not valid():raise RuntimeError('Контрольная сумма LibreOffice не совпала.')
            return path
        except Exception as exc:
            print('Параллельная загрузка недоступна ('+type(exc).__name__+'); используется основной источник.',flush=True)
    req=urllib.request.Request(url,headers={'User-Agent':'AtlasDemo/0.1'})
    with urllib.request.urlopen(req,timeout=90,context=TLS) as response,temp.open('wb') as output:
        total=int(response.headers.get('Content-Length',0));received=0;last=-1
        while chunk:=response.read(1024*1024):
            output.write(chunk);received+=len(chunk)
            percent=int(received*100/total) if total else received//1048576
            if percent//5!=last:
                print(f'{name}: {received//1048576} МБ'+(f' / {total//1048576} МБ' if total else ''),flush=True);last=percent//5
    temp.replace(path)
    if not valid():raise RuntimeError('Контрольная сумма '+name+' не совпала. Повторите запуск.')
    return path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--converter',action='store_true');args=parser.parse_args()
    font=ROOT/'vendor/fonts/NotoSans-Regular.ttf'
    if not font.exists() or hashlib.sha256(font.read_bytes()).hexdigest()!=ASSETS['font'][1]:
        font.parent.mkdir(parents=True,exist_ok=True);font.write_bytes(download('font').read_bytes())
    pdfjs=ROOT/'vendor/pdfjs'
    if not (pdfjs/'pdf.mjs').exists() or not (pdfjs/'pdf.worker.mjs').exists():
        archive=download('pdfjs');pdfjs.mkdir(parents=True,exist_ok=True)
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                name=member.name
                if name in ('package/build/pdf.mjs','package/build/pdf.worker.mjs','package/LICENSE'):dest=pdfjs/Path(name).name
                elif any(name.startswith('package/'+folder+'/') for folder in ('cmaps','standard_fonts','wasm')) and member.isfile():dest=pdfjs/Path(name).relative_to('package')
                else:continue
                if member.isfile():dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(tar.extractfile(member).read())
    if args.converter:
        folder=ROOT/'runtime/libreoffice'
        if not list(folder.glob('**/soffice.exe')):
            package=download('libreoffice');print('Распаковка LibreOffice Portable. Подождите...',flush=True)
            folder.mkdir(parents=True,exist_ok=True)
            # Extract the portable archive directly: no installer GUI, registry or EULA wizard.
            tools=ROOT/'vendor/7zip';manifest=json.loads((tools/'manifest.json').read_text(encoding='utf-8-sig'))
            for name,expected in manifest['sha256'].items():
                if hashlib.sha256((tools/name).read_bytes()).hexdigest()!=expected:raise RuntimeError('Повреждён локальный распаковщик 7-Zip.')
            subprocess.run([str(tools/'7z.exe'),'x',str(package),'-o'+str(folder),'-y','-bso0','-bsp0','App/libreoffice/*'],
                           check=True,timeout=600,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            if not list(folder.glob('**/soffice.exe')):raise RuntimeError('Не найден soffice.exe после распаковки LibreOffice.')
        print('LibreOffice Portable готов.',flush=True)
    print('Локальные шрифты и PDF.js готовы.',flush=True)

if __name__=='__main__':main()
