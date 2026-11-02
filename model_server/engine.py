import gc
import json
import threading
from shared.settings import ROOT,settings,configure_offline

configure_offline()
MANIFEST=json.loads((ROOT/'config/models.json').read_text(encoding='utf-8'))

class Engine:
    def __init__(self):
        self.lock=threading.Lock();self.loaded=None;self.model=None;self.device='cpu';self.current=None;self.error=None;self.cpu_only=set()

    def status(self):
        return {'device':self.device,'requested_device':settings()['device'],'current':self.current,
                'loaded':self.loaded,'error':self.error,'cpu_fallback_models':sorted(self.cpu_only),
                'models':{k:dict(v,downloaded=(ROOT/'models'/v['folder']/'.complete').exists()) for k,v in MANIFEST.items()}}

    def load(self,kind,force_cpu=False):
        import torch
        cfg=settings();requested=cfg['device']
        torch.set_num_threads(cfg.get('cpu_threads',4))
        force_cpu=force_cpu or kind in self.cpu_only
        device='cpu'
        if not force_cpu and requested!='cpu' and torch.cuda.is_available():
            try:
                free,total=torch.cuda.mem_get_info()
                if free>768*1024**2:
                    torch.cuda.set_per_process_memory_fraction(min(.95,cfg['vram_budget_mb']*1024**2/total))
                    (torch.ones(1,device='cuda')+1).cpu();device='cuda'
            except Exception:device='cpu'
        if self.loaded==kind and self.device==device:return
        self.model=None;self.loaded=None;gc.collect()
        self.device=device
        if torch.cuda.is_available():torch.cuda.empty_cache()
        path=ROOT/'models'/MANIFEST[kind]['folder']
        if not (path/'.complete').exists():raise RuntimeError('Модель не скачана. Запустите start_models.bat.')
        if kind=='embedding':
            from sentence_transformers import SentenceTransformer
            model=SentenceTransformer(str(path),local_files_only=True,device=device)
        else:
            from gliner.model import UniEncoderSpanGLiNER
            from transformers import AutoTokenizer
            class LocalGLiNER(UniEncoderSpanGLiNER):
                @classmethod
                def _load_tokenizer(cls,config,model_dir,cache_dir=None):
                    # Transformers 4.57.3 mistakes legacy local configs lacking
                    # transformers_version for Mistral. Keep mDeBERTa's tokenizer
                    # unchanged; GLiNER requires fast word_ids(), not a slow tokenizer.
                    source=model_dir if (model_dir/'tokenizer_config.json').exists() else config.model_name
                    return AutoTokenizer.from_pretrained(source,local_files_only=True,
                        fix_mistral_regex=False,model_max_length=384)
            model=LocalGLiNER.from_pretrained(str(path),local_files_only=True,load_tokenizer=True,strict=True)
            model.to(device)
        model.eval()
        # FP32 is portable; small batch and one loaded model keep memory bounded.
        self.model=model;self.loaded=kind;self.device=device

    def _embedding(self,items):
        import numpy as np
        # Chunk by tokenizer tokens, never truncate an unprocessed suffix.
        tokenizer=self.model.tokenizer;limit=max(8,self.model.max_seq_length-4)
        chunks=[];owners=[]
        for idx,item in enumerate(items):
            ids=tokenizer.encode(item['text'],add_special_tokens=False,verbose=False)
            for start in range(0,max(len(ids),1),limit):
                chunks.append(tokenizer.decode(ids[start:start+limit],skip_special_tokens=True));owners.append(idx)
        batch=4 if self.device=='cuda' else 8
        while True:
            try:
                vectors=self.model.encode(chunks,batch_size=batch,normalize_embeddings=True,show_progress_bar=False)
                break
            except RuntimeError as exc:
                if 'out of memory' not in str(exc).lower() or batch==1:raise
                batch=max(1,batch//2)
                import torch
                torch.cuda.empty_cache()
        output=[]
        for idx,item in enumerate(items):
            vec=np.mean([v for owner,v in zip(owners,vectors) if owner==idx],axis=0)
            norm=np.linalg.norm(vec)
            output.append({'id':item['id'],'vector':(vec/(norm or 1)).tolist()})
        return output

    def _entities(self,items):
        output=[]
        labels=['organization','money','date','bank account','tax identifier']
        tokenizer=self.model.data_processor.transformer_tokenizer
        for item in items:
            text=item['text'];entities=[];start=0
            # Bound actual subword tokens, including pathological long words.
            # Overlap preserves entity context; offsets always reference original text.
            while start<len(text):
                end=min(start+1200,len(text))
                while end>start+1 and len(tokenizer.encode(text[start:end],add_special_tokens=False,verbose=False))>256:
                    end=start+max(1,(end-start)//2)
                for entity in self.model.predict_entities(text[start:end],labels,threshold=settings()['entity_threshold']):
                    a=entity['start']+start;b=entity['end']+start
                    if text[a:b]!=entity['text']:continue
                    value={'start':a,'end':b,'text':text[a:b],'label':entity['label'],'score':float(entity['score'])}
                    if not any(e['start']==a and e['end']==b and e['label']==value['label'] for e in entities):entities.append(value)
                if end==len(text):break
                start=max(start+1,end-min(120,(end-start)//3))
            output.append({'id':item['id'],'entities':entities})
        return output

    def execute(self,kind,items):
        import torch
        with self.lock:
            self.current=kind;self.error=None
            try:
                try:
                    self.load(kind)
                    with torch.inference_mode():output=self._embedding(items) if kind=='embedding' else self._entities(items)
                except RuntimeError as exc:
                    if self.device!='cuda' or 'out of memory' not in str(exc).lower():raise
                    self.cpu_only.add(kind)
                    print('Недостаточно видеопамяти. Модель '+kind+' переводится на CPU до перезапуска.',flush=True)
                    self.load(kind,force_cpu=True)
                    with torch.inference_mode():output=self._embedding(items) if kind=='embedding' else self._entities(items)
                return {'model':MANIFEST[kind], 'device':self.device,'items':output}
            except Exception as exc:
                self.error=type(exc).__name__;raise
            finally:self.current=None

engine=Engine()
