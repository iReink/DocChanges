import argparse,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--device',default='cpu');parser.add_argument('--embedding-only',action='store_true');parser.add_argument('--entities-only',action='store_true');args=parser.parse_args()
    os.environ['ATLAS_DEVICE']=args.device
    from model_server.engine import engine
    import torch
    stats={}
    tasks=[('embedding',[{'id':'short','text':'Срок поставки составляет десять рабочих дней.'},{'id':'long','text':'Условия поставки. '*200+'Последний пункт договора.'}])]
    if not args.embedding_only:
        tasks.append(('entities',[{'id':'contract','text':'Компания ООО «Альфа» заключила договор с ООО «Бета» на сумму 500 000 рублей.'},
                                  {'id':'long','text':'Поставка материалов по договору. '*80+' ООО «Альфа»'}]))
    if args.entities_only:tasks=[t for t in tasks if t[0]=='entities']
    for kind,items in tasks:
        print('Проверка '+kind+' на '+args.device,flush=True)
        if torch.cuda.is_available():torch.cuda.reset_peak_memory_stats()
        start=time.perf_counter();result=engine.execute(kind,items)
        entry={'seconds':round(time.perf_counter()-start,3),'device':result['device'],'model':result['model']}
        if kind=='embedding':
            assert all(len(x['vector'])==384 for x in result['items']);entry['dimensions']=384
        else:
            assert any(x['entities'] for x in result['items']),result
            for item,value in zip(items,result['items']):
                assert all(item['text'][e['start']:e['end']]==e['text'] for e in value['entities'])
            entry['entities']=result['items']
        if torch.cuda.is_available():
            entry['peak_allocated_mb']=round(torch.cuda.max_memory_allocated()/1048576,2)
            entry['peak_reserved_mb']=round(torch.cuda.max_memory_reserved()/1048576,2)
        stats[kind]=entry;print(json.dumps(entry,ensure_ascii=False),flush=True)
    target=ROOT/'work'/('models-'+args.device+('-embedding' if args.embedding_only else '-entities' if args.entities_only else '')+'.json')
    target.write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
