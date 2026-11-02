import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import httpx
from shared import VERSION
from shared.schema import serialise
from shared.settings import settings
from .extract import extract, pdf_content
from .diff import compare, similarity, party_name_spans
from .signatures import inspect_signatures

def model_call(endpoint,payload):
    cfg=settings()
    with httpx.Client(timeout=cfg['model_timeout_seconds'],trust_env=False) as client:
        response=client.post(cfg['models_url']+'/api/v1/'+endpoint,json=payload)
        response.raise_for_status()
        return response.json()

def run(job_folder: Path,meta,progress):
    started=time.perf_counter();timings={};revision=0
    progress('Подготовка документов')
    docs={}
    warnings=[];models={};ai_state='not_used'
    for side in ('old','new'):
        folder=job_folder/side;folder.mkdir(exist_ok=True)
        docs[side]=extract(folder/'original',meta[side]['name'],folder,structure_only=True)
        warnings.extend(docs[side].warnings)
    old,new=docs['old'],docs['new']
    mixed=(old.format=='pdf') != (new.format=='pdf')
    if mixed:
        # Each edition is parsed independently. Never partition one edition's
        # text using the changed edition's Word paragraphs as a template.
        progress('Подготовка независимых представлений документов')
        for side,doc in list(docs.items()):
            if doc.format!='pdf':
                doc=extract(job_folder/side/'original',meta[side]['name'],job_folder/side)
                doc.blocks=pdf_content(Path(doc.preview))[0]
                doc.coverage['tables']='reconstructed'
                docs[side]=doc
                warnings.extend(doc.warnings)
        old,new=docs['old'],docs['new']
    if old.format=='pdf' or new.format=='pdf':
        from .pdf_structure import logical_pdf
        old,new=logical_pdf(old),logical_pdf(new)
        docs['old'],docs['new']=old,new
    if old.format=='pdf' or new.format=='pdf':
        warnings.append('Изменения границ абзацев и переносов для пар с PDF не проверялись.')
        old.coverage['formatting']=new.coverage['formatting']='not_applicable'
    timings['preparation_seconds']=round(time.perf_counter()-started,3)
    unavailable=any(d.coverage.get('text')=='unavailable' or any('нет доступного текста' in w for w in d.warnings) for d in docs.values())
    changes=[] if unavailable else compare(old,new)
    signatures={'old':[],'new':[]}
    def assemble(provisional=False):
        docmeta={side:{key:getattr(doc,key) for key in ('name','format','sha256','pages','coverage')} for side,doc in docs.items()}
        navigation_partial=any(d.coverage['navigation']=='partial' for d in docs.values())
        content_warnings=[w for w in warnings if not w.startswith('Не удалось точно привязать к страницам')]
        return {'id':meta['id'],'employee':meta['employee'],
                'compared_at':datetime.now(ZoneInfo('Asia/Yekaterinburg')).isoformat(),
                'documents':docmeta,'count':len(changes),'changes':[serialise(c) for c in changes],
                'summary':'Сравнение текста невозможно: есть страницы без текстового слоя. OCR выключен.' if unavailable else ('В документах выявлены различия' if changes else 'Различий в документах не выявлено'),
                'comparison_status':'unavailable' if unavailable else 'compared',
                'partial':bool(content_warnings),'navigation_partial':navigation_partial,
                'warnings':list(dict.fromkeys(warnings)),'signatures':signatures,
                'algorithm_version':VERSION,'models':dict(models),'ai_state':ai_state,
                'provisional':provisional,'revision':revision,'timings':dict(timings),
                'checks':{'text':'unavailable' if unavailable else ('partial' if any(d.coverage.get('text')=='partial' for d in docs.values()) else 'complete'),
                          'classification':'not_performed' if unavailable else ('pending' if provisional else 'complete'),
                          'signatures':'not_checked' if unavailable else ('pending' if provisional else 'complete'),
                          'previews':'pending' if any(not d.pages for d in docs.values()) else 'complete'}}
    def publish():
        nonlocal revision
        revision+=1
        data=assemble(True)
        pending=job_folder/f'snapshot-{revision}.pending'
        pending.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        # Immutable versioned snapshots avoid replacing a file while Windows
        # readers hold it open. The API sees only fully written .json files.
        pending.rename(job_folder/f'snapshot-{revision}.json')
    timings['first_result_seconds']=round(time.perf_counter()-started,3)
    publish()
    if unavailable:
        revision+=1;timings['total_seconds']=round(time.perf_counter()-started,3)
        result=assemble()
        (job_folder/'result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        return result
    if any(not d.pages for d in docs.values()):
        progress('Подготовка страниц — текстовые изменения уже доступны')
        existing={(c.operation,c.old_paragraph,c.new_paragraph,c.before,c.after):c.id for c in changes}
        for side in ('old','new'):
            if not docs[side].pages:
                docs[side]=extract(job_folder/side/'original',meta[side]['name'],job_folder/side)
                warnings.extend(docs[side].warnings)
                old,new=docs['old'],docs['new']
                if old.format=='pdf' or new.format=='pdf':old.coverage['formatting']=new.coverage['formatting']='not_applicable'
                changes=compare(old,new)
                for c in changes:c.id=existing.get((c.operation,c.old_paragraph,c.new_paragraph,c.before,c.after),c.id)
                timings[side+'_preview_seconds']=round(time.perf_counter()-started,3)
                publish()
        timings['previews_ready_seconds']=round(time.perf_counter()-started,3)
    progress('Сопоставление структуры')
    semantic={}
    # Restrict semantic work to blocks without a strong lexical counterpart.
    unresolved=[]
    unmatched_old={c.before for c in changes if c.operation=='delete' and not c.details}
    unmatched_new={c.after for c in changes if c.operation=='insert' and not c.details}
    for side,doc,other in [('old',old,new),('new',new,old)]:
        for i,b in enumerate(doc.blocks):
            candidates=unmatched_old if side=='old' else unmatched_new
            if unmatched_old and unmatched_new and b.kind=='paragraph' and b.text in candidates:
                unresolved.append({'id':f'{side}:{i}','text':b.text})
    if unresolved:
        try:
            response=model_call('embeddings',{'fragments':unresolved})
            models['embedding']=response['model'];ai_state='used'
            vectors={v['id']:v['vector'] for v in response['items']}
            for key,vec in vectors.items():
                if not key.startswith('old:'):continue
                i=int(key.split(':')[1]);scores=[]
                for key2,v2 in vectors.items():
                    if not key2.startswith('new:'):continue
                    denom=math.sqrt(sum(x*x for x in vec)*sum(x*x for x in v2))
                    scores.append((sum(x*y for x,y in zip(vec,v2))/denom if denom else 0,int(key2.split(':')[1])))
                scores.sort(reverse=True)
                if scores and (len(scores)==1 or scores[0][0]-scores[1][0]>=settings()['alignment_margin']):
                    semantic[i,scores[0][1]]=scores[0][0]
        except Exception:
            warnings.append('Семантическое сопоставление ИИ недоступно; использованы код и структурные признаки.');ai_state='unavailable'
    progress('Поиск точных изменений')
    if semantic:
        existing={(c.operation,c.old_paragraph,c.new_paragraph,c.before,c.after):c.id for c in changes}
        changes=compare(old,new,semantic)
        for c in changes:c.id=existing.get((c.operation,c.old_paragraph,c.new_paragraph,c.before,c.after),c.id)
        publish()
    progress('Классификация изменений')
    fragments=[];contexts={};targets={}
    for c in changes:
        if c.operation not in ('replace','insert','delete') or 'formatting' in c.categories:continue
        for side in ('old','new'):
            text=c.details.get(side+'_context')
            if text:
                if text not in contexts:
                    fid=str(len(contexts));contexts[text]=fid
                    fragments.append({'id':fid,'text':text});targets[fid]=[]
                targets[contexts[text]].append((c,side))
    if fragments:
        try:
            response=model_call('entities',{'fragments':fragments})
            models['entities']=response['model'];ai_state='used' if ai_state!='unavailable' else 'partial'
            cats={'organization':'parties','money':'money','date':'dates','bank account':'requisites','tax identifier':'requisites'}
            for item in response['items']:
                for c,side in targets.get(item['id'],[]):
                    spans=[f[side+'_range'] for f in c.details.get('fragments',[])] or [c.details.get(side+'_range',[0,0])]
                    offset=c.details.get(side+'_context_offset',0);context=c.details.get(side+'_context','')
                    for entity in item['entities']:
                        start,end=entity['start'],entity['end']
                        if not (0<=start<end<=len(context)) or context[start:end]!=entity['text']:continue
                        if entity['score']<settings()['entity_threshold'] or not any(end>lo+offset and start<hi+offset for lo,hi in spans):continue
                        category=cats.get(entity['label'])
                        if category=='parties' and not any(end>lo and start<hi for lo,hi in party_name_spans(context)):continue
                        if category and category not in c.categories:
                            c.categories.append(category);c.source='rules+gliner'
                            if 'text' in c.categories:c.categories.remove('text')
        except Exception:
            warnings.append('Классификация сущностей ИИ недоступна; все найденные правки сохранены с категориями правил.');ai_state='partial' if ai_state=='used' else 'unavailable'
    timings['classification_finished_seconds']=round(time.perf_counter()-started,3)
    publish()
    progress('Проверка сведений о подписях')
    signatures={}
    for side in ('old','new'):
        sigfiles=sorted((job_folder/side).glob('signature-*'))
        signatures[side]=inspect_signatures(job_folder/side/'original',sigfiles,docs[side].format)
        docs[side].coverage['signatures']='integrity_only' if signatures[side] else 'not_provided'
        if any(s.get('mathematical')!='valid' for s in signatures[side]):warnings.append('Часть подписей не проверена или проверка не пройдена. См. вкладку подписей.')
    # Signature set changes are separate, non-text events.
    from .diff import event
    def fingerprints(items):return sorted((x.get('fingerprint',''),x.get('algorithm_name',''),x.get('container',''),x.get('mathematical',''),str(x.get('later_revisions',''))) for x in items if not x.get('inspection_error'))
    if fingerprints(signatures['old'])!=fingerprints(signatures['new']):
        change=event('signature_change',None,None,json.dumps(signatures['old'],ensure_ascii=False),json.dumps(signatures['new'],ensure_ascii=False),categories=['signatures'])
        changes.append(change)
    progress('Подготовка результата')
    revision+=1;timings['total_seconds']=round(time.perf_counter()-started,3)
    result=assemble()
    (job_folder/'result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    return result
