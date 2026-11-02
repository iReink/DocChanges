import json
from shared.schema import Document,Block,Location
import comparison_server.pipeline as pipeline


def test_scan_does_not_turn_missing_text_into_deletions(tmp_path,monkeypatch):
    def extraction(path,name,folder,structure_only=False):
        scan=name=='scan.pdf'
        return Document(name,'pdf','hash',[] if scan else [Block('a','paragraph','Цена 100 рублей',1)],1,
                        ['Страница 1: нет доступного текста; OCR выключен.'] if scan else [],'',
                        {'text':'unavailable' if scan else 'complete','tables':'reconstructed','navigation':'complete'})
    monkeypatch.setattr(pipeline,'extract',extraction)
    monkeypatch.setattr(pipeline,'model_call',lambda *a:(_ for _ in ()).throw(AssertionError('No model calls for unreadable text')))
    r=pipeline.run(tmp_path,{'id':'test','employee':'Тест','old':{'name':'text.pdf'},'new':{'name':'scan.pdf'}},lambda _:None)
    assert r['comparison_status']=='unavailable' and r['count']==0 and r['changes']==[]
    assert r['checks']['text']=='unavailable' and r['checks']['classification']=='not_performed'
    assert 'невозможно' in r['summary'] and not r['provisional']


def test_mixed_pair_uses_words_own_render_not_other_editions_boundaries(tmp_path,monkeypatch):
    own=tmp_path/'word-own-preview.pdf';calls=[]
    def extraction(path,name,folder,structure_only=False):
        word=name.endswith('.docx')
        return Document(name,'docx' if word else 'pdf','hash',
                        [Block('w' if word else 'p','paragraph','XML boundary' if word else '1. Одинаковый текст')],
                        0 if word and structure_only else 1,[],str(own) if word else 'other.pdf',
                        {'text':'complete','tables':'complete','navigation':'complete'})
    def content(path):
        calls.append(path)
        assert path==own
        return [Block('own','paragraph','1. Одинаковый текст')],[],1,[]
    monkeypatch.setattr(pipeline,'extract',extraction);monkeypatch.setattr(pipeline,'pdf_content',content)
    monkeypatch.setattr(pipeline,'inspect_signatures',lambda *a:[])
    r=pipeline.run(tmp_path,{'id':'test','employee':'Тест','old':{'name':'old.docx'},'new':{'name':'new.pdf'}},lambda _:None)
    assert calls==[own] and r['count']==0 and r['comparison_status']=='compared'


def test_text_snapshot_precedes_word_rendering(tmp_path,monkeypatch):
    calls=[]
    def extraction(path,name,folder,structure_only=False):
        calls.append((name,structure_only))
        coverage={'text':'complete','tables':'complete','formatting':'paragraphs_and_breaks',
                  'navigation':'pending' if structure_only else 'complete','signatures':'not_checked'}
        if not structure_only:
            snapshot=json.loads((tmp_path/'snapshot-1.json').read_text(encoding='utf8'))
            assert snapshot['provisional'] and snapshot['count']==1 and snapshot['checks']['previews']=='pending'
        value='Цена 100 рублей' if name=='old.docx' else 'Цена 200 рублей'
        return Document(name,'docx','hash',[Block(name,'paragraph',value,1)],0 if structure_only else 1,[],str(folder/'preview.pdf'),coverage)
    monkeypatch.setattr(pipeline,'extract',extraction)
    monkeypatch.setattr(pipeline,'inspect_signatures',lambda *a:[])
    monkeypatch.setattr(pipeline,'model_call',lambda *a:(_ for _ in ()).throw(ConnectionError()))
    result=pipeline.run(tmp_path,{'id':'test','employee':'Тест','old':{'name':'old.docx'},'new':{'name':'new.docx'}},lambda _:None)
    assert calls[:2]==[('old.docx',True),('new.docx',True)]
    assert not result['provisional'] and result['checks']['previews']=='complete'
    early=json.loads((tmp_path/'snapshot-1.json').read_text(encoding='utf8'))
    assert early['changes'][0]['id']==result['changes'][0]['id']
    intermediate=json.loads((tmp_path/'snapshot-2.json').read_text(encoding='utf8'))
    assert intermediate['documents']['old']['pages']==1 and intermediate['documents']['new']['pages']==0


def test_navigation_failure_does_not_mark_text_incomplete(tmp_path,monkeypatch):
    def extraction(path,name,folder,structure_only=False):
        return Document(name,'docx','hash',[Block('a','paragraph','Одинаковый текст',1)],1,
                        ['Не удалось точно привязать к страницам 1 текстовых блоков Word.'],'',
                        {'text':'complete','tables':'complete','navigation':'partial','signatures':'not_checked'})
    monkeypatch.setattr(pipeline,'extract',extraction)
    monkeypatch.setattr(pipeline,'inspect_signatures',lambda *a:[])
    result=pipeline.run(tmp_path,{'id':'test','employee':'Тест','old':{'name':'old.docx'},'new':{'name':'new.docx'}},lambda _:None)
    assert not result['partial'] and result['navigation_partial'] and result['count']==0


def test_signature_inspection_error_is_a_limitation_not_a_changed_signature(tmp_path,monkeypatch):
    def extraction(path,name,folder,structure_only=False):
        return Document(name,'docx','hash',[Block('a','paragraph','Одинаковый текст',1)],1,[],'',
                        {'text':'complete','tables':'complete','navigation':'complete','signatures':'not_checked'})
    monkeypatch.setattr(pipeline,'extract',extraction)
    monkeypatch.setattr(pipeline,'inspect_signatures',lambda path,*args:
                        [{'inspection_error':True,'container':'pdf','mathematical':'not_checked'}] if path.parent.name=='new' else [])
    result=pipeline.run(tmp_path,{'id':'test','employee':'Тест','old':{'name':'old.docx'},'new':{'name':'new.docx'}},lambda _:None)
    assert result['count']==0 and result['partial'] and result['warnings']


def test_ner_organisation_is_not_automatically_a_party(tmp_path,monkeypatch):
    old='Покупатель передает спор суду Российской Федерации по месту нахождения Продавца.'
    new='Покупатель передает спор суду Республики Казахстан по месту нахождения Продавца.'
    def extraction(path,name,folder,structure_only=False):
        return Document(name,'docx','hash',[Block(name,'paragraph',old if name=='old.docx' else new,1)],1,[],'',
                        {'text':'complete','tables':'complete','navigation':'complete','signatures':'not_checked'})
    def model_call(endpoint,payload):
        assert endpoint=='entities'
        items=[]
        for fragment in payload['fragments']:
            text=fragment['text'];entity='Российской Федерации' if 'Российской' in text else 'Республики Казахстан'
            start=text.index(entity)
            items.append({'id':fragment['id'],'entities':[{'label':'organization','text':entity,'start':start,'end':start+len(entity),'score':.99}]})
        return {'model':'test-ner','items':items}
    monkeypatch.setattr(pipeline,'extract',extraction)
    monkeypatch.setattr(pipeline,'inspect_signatures',lambda *a:[])
    monkeypatch.setattr(pipeline,'model_call',model_call)
    result=pipeline.run(tmp_path,{'id':'test','employee':'Тест','old':{'name':'old.docx'},'new':{'name':'new.docx'}},lambda _:None)
    assert result['ai_state']=='used' and result['changes']
    assert all('parties' not in c['categories'] for c in result['changes'])
