"""Run every directed file combination through an already running Atlas API."""
import argparse,hashlib,json,time
from pathlib import Path
import httpx


def main():
    parser=argparse.ArgumentParser(description='Проверка всех сочетаний документов через API Атласа')
    parser.add_argument('directory',type=Path,help='Папка с тестовыми DOC/DOCX/PDF')
    parser.add_argument('--url',default='http://localhost:8000')
    parser.add_argument('--output',type=Path,default=Path('work/matrix'))
    args=parser.parse_args()
    files=sorted(p for p in args.directory.iterdir() if p.suffix.lower() in ('.doc','.docx','.pdf'))
    if not files:parser.error('В папке нет документов.')
    args.output.mkdir(exist_ok=True,parents=True);rows=[]
    print(f'Файлов: {len(files)}. Сравнений, включая обратные и самосравнения: {len(files)**2}',flush=True)
    with httpx.Client(base_url=args.url,timeout=180,trust_env=False) as client:
        for a in files:
            for b in files:
                with a.open('rb') as x,b.open('rb') as y:
                    response=client.post('/api/v1/comparisons',data={'employee':'Проверка матрицы'},files={'old':(a.name,x),'new':(b.name,y)})
                response.raise_for_status();jid=response.json()['id'];started=time.monotonic()
                while True:
                    state=client.get('/api/v1/comparisons/'+jid);state.raise_for_status();state=state.json()
                    if state['state'] not in ('queued','running'):break
                    if time.monotonic()-started>960:raise TimeoutError(jid)
                    time.sleep(1)
                row={'old':a.name,'new':b.name,'id':jid,'state':state['state']}
                if state['state']=='completed':
                    report=client.get(f'/api/v1/comparisons/{jid}/result');report.raise_for_status();data=report.json()
                    for side,path in [('old',a),('new',b)]:
                        assert data['documents'][side]['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
                    row.update(count=data['count'],comparison_status=data.get('comparison_status'),checks=data['checks'])
                    (args.output/(jid+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
                else:row['error']=state.get('error')
                rows.append(row)
                (args.output/'matrix.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(row,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
