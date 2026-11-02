"""Independently replay exported character edits against the source DOCX text."""
import argparse
import json
from collections import defaultdict
from pathlib import Path
from comparison_server.extract import extract


def audit(old_path,new_path,result,folder):
    docs=[]
    for side,path in [('old',old_path),('new',new_path)]:
        target=folder/side;target.mkdir(parents=True,exist_ok=True)
        docs.append(extract(path,path.name,target,structure_only=True))
    def texts(doc):
        blocks=[c for b in doc.blocks for row in b.rows for c in row]+[b for b in doc.blocks if b.kind!='table']
        return {b.paragraph:b.text for b in blocks}
    old,new=map(texts,docs);groups=defaultdict(list)
    for c in result['changes']:
        if c['details'].get('fragments'):
            groups[c['old_paragraph'],c['new_paragraph']].extend(c['details']['fragments'])
    checked=[]
    for (a,b),fragments in groups.items():
        before,after=old[a],new[b];text='';cursor=0
        for f in sorted(fragments,key=lambda f:(*f['old_range'],*f['new_range'])):
            lo,hi=f['old_range'];nl,nh=f['new_range']
            assert cursor<=lo<=hi<=len(before),(a,b,'overlap')
            assert before[lo:hi]==f['before'] and after[nl:nh]==f['after'],(a,b,'range')
            text+=before[cursor:lo]+f['after'];cursor=hi
        assert text+before[cursor:]==after,(a,b,'reconstruction')
        checked.append({'old_paragraph':a,'new_paragraph':b,'fragments':len(fragments)})
    return {'algorithm_version':result['algorithm_version'],'count':result['count'],
            'reconstructed_blocks':len(checked),'blocks':checked,
            'movements':[{'operation':c['operation'],'old_paragraph':c['old_paragraph'],
                          'new_paragraph':c['new_paragraph'],'renumbered':c['details'].get('renumbered',False)}
                         for c in result['changes'] if 'movement' in c['categories']]}


def main():
    parser=argparse.ArgumentParser()
    for name in ('old','new','result','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    data=audit(args.old,args.new,json.loads(args.result.read_text(encoding='utf8')),args.output)
    (args.output/'audit.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(data,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
