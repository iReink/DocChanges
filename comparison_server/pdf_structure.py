"""PDF-only logical blocks: page furniture is compared outside the body.

No words or punctuation are normalised away. Only verified page counters and
repeated occurrences of the same running header/footer are canonicalised.
"""
import re
from dataclasses import replace
from .diff import combine, normal


def logical_pdf(document):
    body=[b for b in document.blocks if b.area=='body']
    merged=[]
    for block in body:
        previous=merged[-1] if merged else None
        if previous and previous.kind==block.kind=='paragraph' and previous.locations and block.locations:
            last,first=previous.locations[-1],block.locations[0]
            numbered=bool(re.match(r'^\d+(?:\.\d+)*\.\s',previous.text))
            continuation=bool(re.match(r'^[а-яёa-z(]',block.text))
            unfinished=not re.search(r'[.!?:;]\s*$',previous.text)
            # Cross-page joins need both a numbered preceding clause and a
            # grammatical continuation. A new heading/numbered clause stays separate.
            if numbered and continuation and unfinished and first.page==last.page+1:
                joined=combine([previous,block])
                merged[-1]=joined
                continue
        merged.append(block)
    extras=[]
    for area in ('header','footer'):
        blocks=[b for b in document.blocks if b.area==area]
        counters={}
        for b in blocks:
            match=re.search(r'(?i)(\b(?:стр\.|page)\s*)(\d+)\s*$',b.text)
            if match and b.locations and int(match[2])==b.locations[0].page:
                key=normal(b.text[:match.start(2)])
                counters.setdefault(key,set()).add(b.locations[0].page)
        seen=set()
        for b in blocks:
            text=b.text
            match=re.search(r'(?i)(\b(?:стр\.|page)\s*)(\d+)\s*$',text)
            if match and b.locations and int(match[2])==b.locations[0].page and len(counters.get(normal(text[:match.start(2)]),set()))>=2:
                text=text[:match.start(2)].rstrip()
            key=normal(text)
            if key not in seen:
                extras.append(replace(b,text=text,locations=[replace(l,end=min(l.end,len(text))) for l in b.locations]))
                seen.add(key)
    # Every body token must survive reconstruction in its original order.
    words=lambda blocks:re.findall(r'\S+', ' '.join(b.text for b in blocks))
    assert words(body)==words(merged)
    return replace(document,blocks=merged+extras+[b for b in document.blocks if b.area not in ('body','header','footer')])
