import zipfile
from pathlib import Path
import pytest
from docx import Document
from comparison_server.extract import read_docx,pdf_content,extract

def test_docx_break_and_table(tmp_path):
    doc=Document();doc.add_paragraph('Первая\nВторая');table=doc.add_table(rows=2,cols=2)
    table.cell(0,0).text='Код';table.cell(0,1).text='Сумма';table.cell(1,0).text='А';table.cell(1,1).text='100'
    path=tmp_path/'test.docx';doc.save(path)
    blocks,warnings=read_docx(path)
    assert blocks[0].text=='Первая\nВторая' and blocks[1].rows[1][1].text=='100'

def test_tracked_changes_rejected(tmp_path):
    from lxml import etree
    doc=Document();doc.add_paragraph('text');path=tmp_path/'x.docx';doc.save(path)
    with zipfile.ZipFile(path) as z:parts={n:z.read(n) for n in z.namelist()}
    tree=etree.fromstring(parts['word/document.xml']);ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    tree.find('.//'+ns+'p').append(etree.Element(ns+'ins'));parts['word/document.xml']=etree.tostring(tree)
    with zipfile.ZipFile(path,'w') as z:
        for name,data in parts.items():z.writestr(name,data)
    with pytest.raises(ValueError,match='исправления'):read_docx(path)

def test_scan_is_not_complete(tmp_path):
    from reportlab.pdfgen import canvas
    path=tmp_path/'scan.pdf';c=canvas.Canvas(str(path));c.rect(50,50,400,600);c.showPage();c.save()
    blocks,warnings,pages,chars=pdf_content(path)
    assert pages==1 and any('OCR' in w for w in warnings)


def test_geometry_across_pages_with_header():
    from comparison_server.extract import attach_geometry
    from shared.schema import Block
    def chars(text):return [{'text':c,'x0':i*5,'x1':i*5+5,'top':10,'bottom':20} for i,c in enumerate(text)]
    block=Block('a','paragraph','Начало условия и продолжение условия')
    assert attach_geometry([block],[chars('Начало условия и '),chars('КОЛОНТИТУЛ продолжение условия')])==0
    assert {l.page for l in block.locations}=={1,2}
    assert len(block.locations)==len(block.text.replace(' ',''))


def test_geometry_does_not_skip_arbitrary_same_page_content():
    from comparison_server.extract import attach_geometry
    from shared.schema import Block
    text='Длинный префикс условия для точного поиска. Неверная вставка окончание'
    chars=[{'text':c,'x0':i,'x1':i+1,'top':10,'bottom':20} for i,c in enumerate(text)]
    block=Block('a','paragraph','Длинный префикс условия для точного поиска. окончание')
    assert attach_geometry([block],[chars])==1 and not block.locations


def test_word_structure_available_without_converter(tmp_path,monkeypatch):
    import comparison_server.extract as module
    doc=Document();doc.add_paragraph('Срок 5 (Пяти) рабочих дней.');path=tmp_path/'x.docx';doc.save(path)
    monkeypatch.setattr(module,'convert',lambda *a:(_ for _ in ()).throw(AssertionError('Converter called too early')))
    value=extract(path,'x.docx',tmp_path,structure_only=True)
    assert value.pages==0 and value.coverage['navigation']=='pending'
    assert value.blocks[0].text=='Срок 5 (Пяти) рабочих дней.'
