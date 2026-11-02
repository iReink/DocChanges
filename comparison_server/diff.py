"""Conservative structural alignment. Embeddings propose matches, never suppress edits."""
import re
import uuid
from difflib import SequenceMatcher
from collections import Counter
from decimal import Decimal,InvalidOperation
from shared.schema import Block, Change, Location, serialise
from shared.settings import settings

LABELS = {'text':'Текст','money':'Суммы','requisites':'Реквизиты','parties':'Стороны','signatures':'Подписи',
          'dates':'Даты и сроки','table':'Таблицы','formatting':'Абзацы и переносы','movement':'Перемещения'}

def normal(text):
    return re.sub(r'\s+', ' ', text).strip()

def similarity(a,b):
    if a.kind != b.kind or a.area != b.area:
        return 0
    x,y = normal(a.text),normal(b.text)
    if x==y:
        return 1
    if not x or not y:
        return 0
    ratio = SequenceMatcher(None,x,y,autojunk=False).ratio()
    if a.kind == 'table':
        ha = ' | '.join(c.text for c in a.rows[0]) if a.rows else ''
        hb = ' | '.join(c.text for c in b.rows[0]) if b.rows else ''
        ratio = max(ratio,.7*SequenceMatcher(None,ha,hb,autojunk=False).ratio()+.2)
    return ratio

def combine(blocks):
    return Block('+'.join(b.id for b in blocks),'paragraph','\n\n'.join(b.text for b in blocks),
                 blocks[0].paragraph, [Location(l.page,l.bbox,l.start+offset,l.end+offset,l.precision)
                 for offset,b in zip([sum(len(x.text)+2 for x in blocks[:i]) for i in range(len(blocks))],blocks)
                 for l in b.locations],area=blocks[0].area)

def _alignment_dp(old,new,semantic=None):
    """Edit-distance sequence alignment with split/join transitions, up to 3 paragraphs."""
    n,m = len(old),len(new)
    dp = [[float('inf')]*(m+1) for _ in range(n+1)]
    prev = {}
    dp[0][0]=0
    cfg=settings()
    for i in range(n+1):
        for j in range(m+1):
            current=dp[i][j]
            options=[]
            if i<n: options.append((i+1,j,1,(1,0,'unmatched')))
            if j<m: options.append((i,j+1,1,(0,1,'unmatched')))
            if i<n and j<m:
                s=similarity(old[i],new[j]); method='lexical'
                if semantic and (i,j) in semantic and s<cfg['alignment_threshold']:
                    es=semantic[(i,j)]
                    if es>=.78 and s>=.15:
                        s=max(s,.65);method='semantic'
                if s>=cfg['alignment_threshold'] or old[i].text==new[j].text:
                    options.append((i+1,j+1,1.6*(1-s),(1,1,method)))
                if old[i].kind==new[j].kind=='paragraph':
                    for count in (2,3):
                        for a,b in ((count,1),(1,count)):
                            if i+a>n or j+b>m: continue
                            aa,bb=old[i:i+a],new[j:j+b]
                            if any(x.kind!='paragraph' or x.area!=aa[0].area for x in aa+bb): continue
                            x=''.join(normal(v.text).replace(' ','') for v in aa)
                            y=''.join(normal(v.text).replace(' ','') for v in bb)
                            score=SequenceMatcher(None,x,y,autojunk=False).ratio()
                            if score>=.94 and x and y:
                                options.append((i+a,j+b,.15+1.6*(1-score),(a,b,'split_join')))
            for ni,nj,cost,step in options:
                candidate=current+cost
                if candidate<dp[ni][nj]:
                    dp[ni][nj]=candidate;prev[ni,nj]=(i,j,step)
    pairs=[];i,j=n,m
    while i or j:
        pi,pj,(a,b,method)=prev[i,j]
        pairs.append((old[pi:i],new[pj:j],method,pi,pj));i,j=pi,pj
    return pairs[::-1]

def alignment(old,new,semantic=None):
    # Anchor unchanged blocks even in small documents: expensive string matching
    # is needed only inside changed gaps, not for every pair of long paragraphs.
    # Exact anchors bound DP memory on long documents. Ambiguous large gaps
    # are kept as explicit deletions/insertions rather than exhausting RAM.
    keys=lambda blocks:[(b.kind,b.area,b.text) for b in blocks]
    ka,kb=keys(old),keys(new);ca,cb=Counter(ka),Counter(kb)
    xa=[k if ca[k]==cb[k]==1 else ('old',i) for i,k in enumerate(ka)]
    xb=[k if ca[k]==cb[k]==1 else ('new',i) for i,k in enumerate(kb)]
    anchors=SequenceMatcher(None,xa,xb,autojunk=False).get_matching_blocks()
    pairs=[];oi=ni=0
    for anchor in anchors:
        a,b=old[oi:anchor.a],new[ni:anchor.b]
        if len(a)*len(b)<=150000:
            local={(i-oi,j-ni):v for (i,j),v in (semantic or {}).items() if oi<=i<anchor.a and ni<=j<anchor.b}
            pairs.extend((aa,bb,method,i+oi,j+ni) for aa,bb,method,i,j in _alignment_dp(a,b,local))
        else:
            pairs.extend(([block],[],'unmatched_large_gap',oi+i,ni) for i,block in enumerate(a))
            pairs.extend(([],[block],'unmatched_large_gap',anchor.a,ni+j) for j,block in enumerate(b))
        pairs.extend(([old[anchor.a+i]],[new[anchor.b+i]],'exact',anchor.a+i,anchor.b+i) for i in range(anchor.size))
        oi,ni=anchor.a+anchor.size,anchor.b+anchor.size
    return pairs

def inn_valid(value):
    if len(value)==10:
        return sum(int(c)*w for c,w in zip(value,[2,4,10,3,5,9,4,6,8]))%11%10==int(value[-1])
    if len(value)==12:
        first=sum(int(c)*w for c,w in zip(value,[7,2,4,10,3,5,9,4,6,8]))%11%10==int(value[10])
        second=sum(int(c)*w for c,w in zip(value,[3,7,2,4,10,3,5,9,4,6,8]))%11%10==int(value[11])
        return first and second
    return False

def rule_entities(text):
    entities=[]
    def owner(position):
        roles=list(re.finditer(r'(?i)заказчик|исполнитель|поставщик|покупатель|продавец',text[:position]))
        return roles[-1][0].lower() if roles else None
    for match in re.finditer(r'(?i)\b(ИНН|КПП|БИК|ОГРНИП|ОГРН)\b\s*(?:[а-яё-]+\s+){0,3}[:№]?\s*(\d{5,20})',text):
        kind,value=match[1].upper(),match[2]
        valid=inn_valid(value) if kind=='ИНН' else len(value)=={'КПП':9,'БИК':9,'ОГРН':13,'ОГРНИП':15}[kind]
        if kind=='ОГРН' and len(value)==13:valid=int(value[:12])%11%10==int(value[-1])
        if kind=='ОГРНИП' and len(value)==15:valid=int(value[:14])%13%10==int(value[-1])
        entities.append({'start':match.start(2),'end':match.end(2),'category':'requisites','field':kind,'value':value,'format_valid':valid,'owner':owner(match.start())})
    for match in re.finditer(r'(?i)(?:[рк]/с|расч[её]тный сч[её]т|корреспондентский сч[её]т)\s*[:№]?\s*(\d{5,25})',text):
        entities.append({'start':match.start(1),'end':match.end(1),'category':'requisites','field':'Счёт','value':match[1],'format_valid':len(match[1])==20})
    for match in re.finditer(r'(?i)(\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d{1,2})?)\s*(руб(?:лей|ля|ль|\.)?|₽|USD|EUR|доллар\w*|евро)',text):
        try:value=str(Decimal(re.sub(r'\s','',match[1]).replace(',','.')))
        except InvalidOperation:value=None
        entities.append({'start':match.start(),'end':match.end(),'category':'money','value':value,'currency':match[2]})
    for match in re.finditer(r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b',text):
        entities.append({'start':match.start(),'end':match.end(),'category':'dates','value':match[0]})
    for match in re.finditer(r'[\w.+-]+@[\w.-]+\.[\w-]+',text):
        entities.append({'start':match.start(),'end':match.end(),'category':'requisites','field':'Email','value':match[0]})
    for match in re.finditer(r'\d+(?:[.,]\d+)?\s*%',text):
        entities.append({'start':match.start(),'end':match.end(),'category':'money','field':'Ставка','value':match[0]})
    return entities

def range_categories(va,vb,old,new,sa,ea,sb,eb,context,table):
    entities=[];cats=[]
    for side,text,start,end in [('old',old,sa,ea),('new',new,sb,eb)]:
        if any(hi>start and lo<end for lo,hi in party_name_spans(text)):cats.append('parties')
        for ent in rule_entities(text):
            if ent['end']>start and ent['start']<end:
                entities.append(dict(ent,side=side));cats.append(ent['category'])
    fallback=classify(va,vb,context+' '+old,context+' '+new,table)
    # Formal field labels elsewhere in the paragraph must not classify unrelated digits.
    for cat in fallback:
        if cat=='parties':continue
        if cat in ('money','requisites','dates') and not table:
            if cat=='dates' and re.search(r'рабоч|календар|дней|день|месяц',va+' '+vb,re.I):cats.append(cat)
            continue
        cats.append(cat)
    cats=list(dict.fromkeys(cats))
    if len(cats)>1 and 'text' in cats:cats.remove('text')
    return cats or ['text'],entities


def party_name_spans(text):
    """Names with explicit party evidence, not every organisation near a role.

    Courts and countries returned by NER are organisations too. A nearby word
    'Покупатель' does not establish that they are a contractual party.
    """
    patterns=[r'(?i:\b(?:ООО|ПАО|ОАО|ЗАО|АО|общество с ограниченной ответственностью|акционерное общество))\s*[«"][^»"\n]+[»"]',
              r'(?i:\b(?:ИП|гражданин(?:ка)?(?: Российской Федерации)?))\s+([А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+)',
              r'(?i:Покупатель|Продавец|Заказчик|Исполнитель)\s*[:\n]\s*([А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+)']
    return [(m.start(1),m.end(1)) if m.lastindex else m.span() for pattern in patterns for m in re.finditer(pattern,text)]

def locations(block,start=None,end=None):
    if not block:return []
    if start is None:return block.locations
    chosen=[l for l in block.locations if l.end>start and l.start<end]
    if chosen:return chosen
    # Breaks and empty inserts have no glyph: highlight nearest available location.
    return sorted(block.locations,key=lambda l:abs(l.start-start))[:1]

def classify(before,after,old_context='',new_context='',table=False):
    cats=['table'] if table else []
    changed=before+' '+after
    context=old_context+' '+new_context
    if re.search(r'\d',changed) and re.search(r'\b(ИНН|КПП|БИК|ОГРН|ОГРНИП)\b|[рк]/с|расч[её]тн\w* сч[её]т|корреспондентск',context,re.I):
        cats.append('requisites')
    if re.search(r'\d|руб|₽|USD|EUR|доллар|евро',changed,re.I) and re.search(r'руб|₽|USD|EUR|доллар|евро|стоимост|цен[аыу]|аванс|оплат|сумм|итого|штраф',context,re.I):
        # Dates and identifiers do not become money merely because the paragraph mentions a sum.
        if 'requisites' not in cats and (re.search(r'руб|₽|USD|EUR|доллар|евро',changed,re.I) or not re.search(r'\d{2}[./]\d{2}[./]\d{4}',changed)):
            cats.append('money')
    if re.search(r'\d{1,2}[./]\d{1,2}[./]\d{2,4}|дн|день|дней|месяц|рабоч|календар',changed,re.I):cats.append('dates')
    if party_name_spans(changed):cats.append('parties')
    return list(dict.fromkeys(cats or ['text']))

def event(operation,a,b,before=None,after=None,details=None,categories=None):
    before=a.text if before is None and a else (before or '')
    after=b.text if after is None and b else (after or '')
    return Change(uuid.uuid4().hex,operation,categories or classify(before,after,a.text if a else '',b.text if b else ''),
                  before,after,locations(a),locations(b),a.paragraph if a else 0,b.paragraph if b else 0,
                  details=details or {})

def field_spans(text):
    """Atomic business values; words in parentheses belong to the same value."""
    number=r'\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?'
    written=r'(?:\s*\([^()\n]+\))?'
    patterns=[('email',r'[\w.+-]+@[\w.-]+\.[\w-]+','requisites'),
              ('money',number+written+r'\s*(?:руб(?:лей|ля|ль|\.)?|₽|USD|EUR|евро|доллар\w*)','money'),
              ('duration',r'\b\d+'+written+r'\s*(?:(?:рабоч\w*|календарн\w*)\s+)?(?:дней|дня|день|суток|сутки|месяц\w*|лет|год\w*|час\w*)\b','dates'),
              ('percent',number+r'\s*%','money'),
              ('date',r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b','dates')]
    result=[]
    for kind,pattern,cat in patterns:
        ordinal=0
        for m in re.finditer(pattern,text,re.I):
            if any(x['start']<m.end() and x['end']>m.start() for x in result):continue
            result.append({'kind':kind,'ordinal':ordinal,'start':m.start(),'end':m.end(),'category':cat})
            ordinal+=1
    return result


def clause_ranges(text):
    # A semicolon connects parts of one condition. Clause numbering is a
    # prefix, not a sentence, and must never become part of an inserted word.
    prefix=re.match(r'^\s*\d+(?:\.\d+)*\.\s+',text)
    starts=[0]+[m.end() for m in re.finditer(r'(?<=[.!?])\s+(?=[А-ЯЁA-Z])',text)
                if not prefix or m.end()>prefix.end()]
    return [(start,starts[i+1] if i+1<len(starts) else len(text)) for i,start in enumerate(starts)]


def numbered_body(block):
    prefix=re.match(r'^\s*(\d+(?:\.\d+)*\.)\s+',block.text) if block.kind=='paragraph' else None
    return (block.kind,block.area,normal(block.text[prefix.end():] if prefix else block.text))


def moved_sentences(a,b):
    """Recognise a pure permutation of unique sentences, without semantic guesses.

    Character edits remain attached to the single parent event so consumers can
    reconstruct the complete paragraph, including whitespace around the move.
    """
    def units(text):
        prefix=re.match(r'^\s*\d+(?:\.\d+)*\.\s+',text)
        start=prefix.end() if prefix else 0
        spans=clause_ranges(text[start:])
        return text[:start],[(normal(text[start+lo:start+hi]),start+lo,start+hi) for lo,hi in spans]
    pa,aa=units(a.text);pb,bb=units(b.text)
    ka=[x[0] for x in aa];kb=[x[0] for x in bb]
    if pa!=pb or ka==kb or len(ka)<2 or Counter(ka)!=Counter(kb) or any(n!=1 for n in Counter(ka).values()):return None
    matcher=SequenceMatcher(None,ka,kb,autojunk=False)
    kept={i for m in matcher.get_matching_blocks() for i in range(m.a,m.a+m.size)}
    result=[]
    for i,(text,lo,hi) in enumerate(aa):
        if i in kept:continue
        j=kb.index(text);_,nl,nh=bb[j]
        change=event('move',a,b,a.text[lo:hi].strip(),b.text[nl:nh].strip(),
                     {'scope':'sentence','old_range':[lo,hi],'new_range':[nl,nh]},['movement'])
        change.old_locations=locations(a,lo,hi);change.new_locations=locations(b,nl,nh)
        result.append(change)
    # Attach the exact paragraph edit script once, avoiding overlapping child edits.
    result[0].details['fragments']=[{'operation':'replace' if x<y and u<v else ('delete' if x<y else 'insert'),
        'before':a.text[x:y],'after':b.text[u:v],'old_range':[x,y],'new_range':[u,v],
        'old_locations':[vars(l) for l in locations(a,x,y)] if x<y else [],
        'new_locations':[vars(l) for l in locations(b,u,v)] if u<v else []}
        for op,x,y,u,v in SequenceMatcher(None,a.text,b.text,autojunk=False).get_opcodes() if op!='equal']
    for c in result:c.details.setdefault('fragments',[])
    return result


def text_changes(a,b,word_pair=True,context='',table=False):
    if a.text==b.text:return []
    if not table:
        moved=moved_sentences(a,b)
        if moved is not None:return moved
    # PDF line wrapping is not a formatting change. Preserve all non-whitespace characters.
    old,new=a.text,b.text
    if not word_pair and normal(old)==normal(new):return []
    # Keep decimal numbers and email addresses atomic for alignment. Character
    # refinement below preserves the exact inserted/deleted characters.
    tokens=lambda text:list(re.finditer(r'[\w.+-]+@[\w.-]+\.[\w-]+|\d+(?:[.,]\d+)*|\w+|[^\w\s]|\s+',text,re.UNICODE))
    ta,tb=tokens(old),tokens(new)
    matcher=SequenceMatcher(None,[t.group() for t in ta],[t.group() for t in tb],autojunk=False)
    groups={};fields={'old':field_spans(old),'new':field_spans(new)}
    clauses={'old':clause_ranges(old),'new':clause_ranges(new)}
    for op,i,j,k,l in matcher.get_opcodes():
        if op=='equal':continue
        sa=ta[i].start() if i<len(ta) else len(old);ea=ta[j-1].end() if j>i else sa
        sb=tb[k].start() if k<len(tb) else len(new);eb=tb[l-1].end() if l>k else sb
        va,vb=old[sa:ea],new[sb:eb]
        if not word_pair and not (va+vb).strip():continue
        formatting=not (va+vb).strip() and '\n' in va+vb
        selected={}
        for side,start,end in [('old',sa,ea),('new',sb,eb)]:
            selected[side]=next((f for f in fields[side] if start< f['end'] and end>f['start']),None)
        paired=selected['old'] and selected['new'] and selected['old']['kind']==selected['new']['kind'] and selected['old']['ordinal']==selected['new']['ordinal']
        if paired:
            key=('field',selected['old']['kind'],selected['old']['ordinal'])
        elif formatting:key=('formatting',sa,sb)
        else:
            indices=[next((n for n,(lo,hi) in enumerate(clauses[side]) if lo<=min(start,max(0,len(text)-1))<hi),0)
                     for side,text,start in [('old',old,sa),('new',new,sb)]]
            key=('clause',*indices)
        group=groups.setdefault(key,{'bounds':[sa,ea,sb,eb],'fragments':[],'field':selected if paired else None,'formatting':formatting})
        bounds=group['bounds'];bounds[:]=[min(bounds[0],sa),max(bounds[1],ea),min(bounds[2],sb),max(bounds[3],eb)]
        for charop,x,y,u,v in SequenceMatcher(None,va,vb,autojunk=False).get_opcodes():
            if charop=='equal':continue
            fa,fe,fb,ff=sa+x,sa+y,sb+u,sb+v
            group['fragments'].append({'operation':'replace' if x<y and u<v else ('delete' if x<y else 'insert'),
                'before':old[fa:fe],'after':new[fb:ff],'old_range':[fa,fe],'new_range':[fb,ff],
                'old_locations':[vars(l) for l in locations(a,fa,fe)] if fa<fe else [],
                'new_locations':[vars(l) for l in locations(b,fb,ff)] if fb<ff else []})
    changes=[]
    for key,g in groups.items():
        sa,ea,sb,eb=g['bounds']
        if g['field']:
            sa,ea=g['field']['old']['start'],g['field']['old']['end']
            sb,eb=g['field']['new']['start'],g['field']['new']['end']
        va,vb=old[sa:ea],new[sb:eb]
        cats,entities=range_categories(va,vb,old,new,sa,ea,sb,eb,context,table)
        if g['field']:cats=[g['field']['old']['category']]+(['table'] if table else [])
        if g['formatting']:cats=['formatting']+(['table'] if table else [])
        if not g['field'] and not g['formatting']:
            # Only the affected clause supplies financial context; a price in an
            # unrelated sentence must not turn a deadline into a sum.
            clause=' '.join(text[lo:hi] for side,text,start in [('old',old,sa),('new',new,sb)]
                            for lo,hi in clauses[side] if lo<=min(start,max(0,len(text)-1))<hi)
            if re.search(r'неустойк|штраф|пошлин|оплат|денежн|расход|аккредитив|задолженн',clause,re.I) and re.search(r'денежн|средств|счет|покрыти|уплач|оплач|расход|Продавец|Покупател|задолженн|погасить|любого одного',va+' '+vb,re.I):cats.append('money')
            if re.search(r'\d.*(?:дн|месяц|лет|год)|рабоч|календар',va+' '+vb,re.I):cats.append('dates')
            if re.search(r'гарантийн\w* срок|срок\w*.*(?:исчисля|начина|с даты|с момента)',clause,re.I) and re.search(r'подписан|регистрац|передач|передаточ|вступлен|получен',va+' '+vb,re.I):cats.append('dates')
        cats=list(dict.fromkeys(cats))
        if len(cats)>1 and 'text' in cats:cats.remove('text')
        details={'old_range':[sa,ea],'new_range':[sb,eb], 'old_context':context+' '+old,'new_context':context+' '+new,
                 'old_context_offset':len(context)+1,'new_context_offset':len(context)+1,'rule_entities':entities,
                 'fragments':g['fragments'],'grouping':key[0],'display_before':va.strip(),'display_after':vb.strip()}
        # A single changed digit still has a readable full word/field, while its
        # exact character range remains in fragments (and in before/after).
        if len(g['fragments'])==1 and not g['field']:
            f=g['fragments'][0]
            for side,text,start,end in [('old',old,sa,ea),('new',new,sb,eb)]:
                if start<end and text[start:end].strip() and text[start:end].strip()==text[start:end] and text[start].isalnum():
                    while start>0 and text[start-1].isalnum():start-=1
                    while end<len(text) and text[end].isalnum():end+=1
                details['display_before' if side=='old' else 'display_after']=text[start:end].strip()
            va,vb=f['before'],f['after']
        change=event('replace' if va and vb else ('delete' if va else 'insert'),a,b,va,vb,details,cats)
        change.old_locations=locations(a,sa,ea) if sa<ea else []
        change.new_locations=locations(b,sb,eb) if sb<eb else []
        changes.append(change)
    return changes

def table_changes(a,b,word_pair):
    changes=[]
    if not a.rows or not b.rows:
        return [event('replace',a,b,categories=['table'])] if a.text!=b.text else []
    # Match column headers structurally. Only treat insert/delete as a whole column
    # when row widths changed, otherwise changed header text is a cell edit.
    ac,bc=len(a.rows[0]),len(b.rows[0])
    if ac!=bc:
        header_pairs=alignment(a.rows[0],b.rows[0])
        colmap=[]
        for aa,bb,_,i,j in header_pairs:
            if aa and bb:colmap.append((i,j))
            elif aa:
                texts='\n'.join(r[i].text for r in a.rows if i<len(r))
                changes.append(event('column_delete',a,None,texts,'',{'column':i+1},['table']))
            else:
                texts='\n'.join(r[j].text for r in b.rows if j<len(r))
                changes.append(event('column_insert',None,b,'',texts,{'column':j+1},['table']))
    else:colmap=list(zip(range(ac),range(bc)))
    def rowblocks(table,side):
        columns=[p[side] for p in colmap]
        return [Block(str(i),'row',' | '.join(row[c].text if c<len(row) else '' for c in columns),row[0].paragraph if row else 0,
                      locations=[l for cell in row for l in cell.locations]) for i,row in enumerate(table.rows)]
    ra,rb=rowblocks(a,0),rowblocks(b,1)
    row_pairs=alignment(ra,rb)
    deleted=[(i,aa[0]) for aa,bb,_,i,j in row_pairs if aa and not bb]
    inserted=[(j,bb[0]) for aa,bb,_,i,j in row_pairs if bb and not aa]
    old_counts=Counter(x.text for x in ra);new_counts=Counter(x.text for x in rb)
    moved_old=set();moved_new=set()
    for i,row in deleted:
        candidate=next(((j,r) for j,r in inserted if r.text==row.text and old_counts[row.text]==new_counts[row.text]==1),None)
        if candidate:
            j,other=candidate;moved_old.add(i);moved_new.add(j)
            changes.append(event('row_move',row,other,details={'old_row':i+1,'new_row':j+1},categories=['table','movement']))
    # A changed value must not destroy row identity when the unique key in the
    # first mapped column is unchanged. Duplicate keys remain ambiguous.
    key=lambda table,index:normal(table.rows[index][colmap[0][0 if table is a else 1]].text) if colmap and table.rows[index] else ''
    ak=[key(a,i) for i in range(len(ra))];bk=[key(b,j) for j in range(len(rb))]
    ka,kb=Counter(ak),Counter(bk)
    identity_pairs=[]
    for i,row in deleted:
        if i in moved_old or i==0 or not ak[i] or ka[ak[i]]!=1 or kb[ak[i]]!=1:continue
        candidate=next(((j,r) for j,r in inserted if j not in moved_new and j>0 and bk[j]==ak[i]),None)
        if candidate:
            j,other=candidate;moved_old.add(i);moved_new.add(j)
            identity_pairs.append(([row],[other],'row_identity',i,j))
    known=[(i,j) for aa,bb,_,i,j in row_pairs+identity_pairs if aa and bb]
    row_pairs+=identity_pairs
    for aa,bb,method,i,j in row_pairs:
        if not aa:
            if j in moved_new:continue
            changes.append(event('row_insert',None,rb[j],details={'row':j+1},categories=['table']));continue
        if not bb:
            if i in moved_old:continue
            changes.append(event('row_delete',ra[i],None,details={'row':i+1},categories=['table']));continue
        # Rows cannot be merged by paragraph split/join transitions.
        if len(aa)>1 or len(bb)>1:
            for item in aa:changes.append(event('row_delete',item,None,categories=['table']))
            for item in bb:changes.append(event('row_insert',None,item,categories=['table']))
            continue
        old_layout=[s[2:] for s in a.spans if s[0]==i]
        new_layout=[s[2:] for s in b.spans if s[0]==j]
        old_flat=''.join(re.sub(r'\s','',c.text) for c in a.rows[i])
        new_flat=''.join(re.sub(r'\s','',c.text) for c in b.rows[j])
        if word_pair and old_layout!=new_layout and old_flat==new_flat:
            changes.append(event('cell_merge',ra[i],rb[j],details={'old_layout':old_layout,'new_layout':new_layout},categories=['table']))
            continue
        first_edit=len(changes)
        for ci,cj in colmap:
            if ci>=len(a.rows[i]) or cj>=len(b.rows[j]):continue
            x,y=a.rows[i][ci],b.rows[j][cj]
            ctx='Столбец: '+a.rows[0][ci].text
            edits=text_changes(x,y,word_pair,ctx,True)
            for change in edits:change.details.update({'old_row':i+1,'new_row':j+1,'old_column':ci+1,'new_column':cj+1})
            changes.extend(edits)
            if word_pair:
                oldspan=next((s[2:] for s in a.spans if s[0]==i and s[1]==ci),[1,0])
                newsp=next((s[2:] for s in b.spans if s[0]==j and s[1]==cj),[1,0])
                if oldspan!=newsp:
                    changes.append(event('cell_merge',x,y,details={'old_span':oldspan,'new_span':newsp},categories=['table']))
        if method=='row_identity' and any((i-x)*(j-y)<0 for x,y in known):
            children=changes[first_edit:];del changes[first_edit:]
            categories=list(dict.fromkeys(['table','movement']+[c for child in children for c in child.categories]))
            changes.append(event('row_move',ra[i],rb[j],details={'old_row':i+1,'new_row':j+1,
                'identity_key':ak[i],'edited':bool(children),'cell_changes':[serialise(c) for c in children]},categories=categories))
    return changes

def compare(old,new,semantic=None):
    word_pair=old.format!='pdf' and new.format!='pdf'
    if not word_pair:
        from .pdf_structure import logical_pdf
        old_ids=[b.id for b in old.blocks];new_ids=[b.id for b in new.blocks]
        old,new=logical_pdf(old),logical_pdf(new)
        old_indices={b.id:i for i,b in enumerate(old.blocks)};new_indices={b.id:i for i,b in enumerate(new.blocks)}
        semantic={(old_indices[old_ids[i]],new_indices[new_ids[j]]):score for (i,j),score in (semantic or {}).items()
                  if i<len(old_ids) and j<len(new_ids) and old_ids[i] in old_indices and new_ids[j] in new_indices}
    pairs=alignment(old.blocks,new.blocks,semantic)
    changes=[];deleted=[];inserted=[]
    for aa,bb,method,i,j in pairs:
        if not aa:
            inserted.append(bb[0]);continue
        if not bb:
            deleted.append(aa[0]);continue
        a=aa[0] if len(aa)==1 else combine(aa)
        b=bb[0] if len(bb)==1 else combine(bb)
        if a.kind=='table':
            changes.extend(table_changes(a,b,word_pair));continue
        if method=='split_join' and normal(a.text)==normal(b.text):
            if word_pair:changes.append(event('paragraph_boundary',a,b,categories=['formatting']))
            continue
        edits=text_changes(a,b,word_pair)
        if method=='semantic':
            for c in edits:c.confidence='semantic_alignment'
        changes.extend(edits)
    # Numbering may change when a whole clause is moved. Require a unique exact
    # body in BOTH complete documents, not merely among unmatched candidates.
    da,ib=Counter(numbered_body(b) for b in old.blocks),Counter(numbered_body(b) for b in new.blocks)
    used=set()
    for a in deleted:
        key=numbered_body(a)
        match=next((b for b in inserted if b.id not in used and numbered_body(b)==key and da[key]==ib[key]==1),None)
        if match:
            number=lambda text:(re.match(r'^\s*(\d+(?:\.\d+)*\.)\s+',text) or [None,''])[1]
            details={'scope':'block','renumbered':number(a.text)!=number(match.text)}
            categories=['movement']
            if a.text!=match.text:
                edits=text_changes(a,match,word_pair)
                details['fragments']=[f for c in edits for f in c.details.get('fragments',[])]
                if any('formatting' in c.categories for c in edits):categories.append('formatting')
            used.add(match.id);changes.append(event('move',a,match,details=details,categories=categories))
        else:
            changes.append(event('table_delete' if a.kind=='table' else 'delete',a,None,categories=['table'] if a.kind=='table' else None))
    for b in inserted:
        if b.id not in used:changes.append(event('table_insert' if b.kind=='table' else 'insert',None,b,categories=['table'] if b.kind=='table' else None))
    return changes
