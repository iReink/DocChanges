"""Measure first/final results against a running comparison API."""
import argparse
import json
import time
from pathlib import Path
import httpx


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--old',type=Path,required=True)
    parser.add_argument('--new',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--url',default='http://localhost:8000')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    events=[];first=None;revision=-1;started=time.perf_counter()
    with httpx.Client(base_url=args.url,timeout=180,trust_env=False) as client:
        with args.old.open('rb') as a,args.new.open('rb') as b:
            response=client.post('/api/v1/comparisons',data={'employee':'Проверка регрессии'},files={'old':(args.old.name,a),'new':(args.new.name,b)})
        response.raise_for_status();jid=response.json()['id']
        print('Задача: '+jid,flush=True)
        (args.output/'task-id.txt').write_text(jid,encoding='utf8')
        for _ in range(1000):
            state=client.get('/api/v1/comparisons/'+jid).json()
            if state.get('result_available') and revision!=state['result_revision']:
                result=client.get(f'/api/v1/comparisons/{jid}/result').json()
                revision=state['result_revision'];elapsed=round(time.perf_counter()-started,3)
                if first is None:first=elapsed
                event={'elapsed_seconds':elapsed,'count':result['count'],'provisional':result['provisional'],'revision':revision}
                events.append(event);print(json.dumps(event,ensure_ascii=False),flush=True)
                (args.output/f'revision-{revision}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
                if result['provisional']:
                    preview=client.get(f'/api/v1/comparisons/{jid}/documents/old/preview')
                    assert preview.status_code in (200,409) if result['checks']['previews']=='pending' else preview.status_code==200
                    report_probe=client.get(f'/api/v1/comparisons/{jid}/reports/docx')
                    # The worker can complete between the snapshot and this request.
                    assert report_probe.status_code in (200,409)
                    if report_probe.status_code==200:
                        assert client.get('/api/v1/comparisons/'+jid).json()['state']=='completed'
            if state['state']=='completed':break
            assert state['state'] not in ('failed','cancelled'),state
            time.sleep(.5)
        assert state['state']=='completed',state
        result=client.get(f'/api/v1/comparisons/{jid}/result').json()
        for fmt in ('docx','pdf','json'):
            report=client.get(f'/api/v1/comparisons/{jid}/reports/{fmt}');report.raise_for_status()
            (args.output/('report.'+fmt)).write_bytes(report.content)
        stats={'task':jid,'first_result_seconds':first,'final_seconds':round(time.perf_counter()-started,3),
               'events':events,'pipeline_timings':result['timings'],'count':result['count'],'ai_state':result['ai_state']}
        (args.output/'metrics.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(stats,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
