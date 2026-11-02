from pathlib import Path
from copy import deepcopy
import re
import pytest
from shared.schema import Block,Document,Location
from comparison_server.pdf_structure import logical_pdf
from comparison_server.diff import compare
from comparison_server.extract import pdf_content


def block(text,page=1,area='body',top=100):
    return Block(text+str(page),'paragraph',text,locations=[Location(page,[80,top,500,top+12],0,len(text),'line')],area=area)


def document(blocks):
    return Document('test.pdf','pdf','',blocks,3,[],'',{})


def test_numbered_clause_continues_across_page_with_offsets():
    a=block('5.1. Сторона обязуется передать',1,top=750)
    b=block('документы до 15 ноября.',2)
    source=document([a,block('Колонтитул',1,'footer',800),block('Заголовок',2,'header',20),b])
    result=logical_pdf(source)
    body=[b for b in result.blocks if b.area=='body']
    assert len(body)==1 and body[0].text==a.text+'\n\n'+b.text
    assert body[0].locations[1].page==2 and body[0].locations[1].start==len(a.text)+2
    assert source.blocks[0].text==a.text  # transformation does not mutate extraction


@pytest.mark.parametrize('following',['6. Ответственность','Новый раздел','2.1. Новое условие.'])
def test_new_section_is_not_joined(following):
    source=document([block('1.1. Передать документы',1),block(following,2)])
    assert len(logical_pdf(source).blocks)==2


def test_completed_clause_is_not_joined():
    source=document([block('1.1. Документы переданы.',1),block('дополнительное условие.',2)])
    assert len(logical_pdf(source).blocks)==2


def test_running_headers_and_verified_counters_do_not_move():
    source=document([block('1. Условие.'),block('Образец',1,'header'),block('Образец',2,'header'),
                     block('Договор №123 | Стр. 1',1,'footer'),block('Договор №123 | Стр. 2',2,'footer')])
    other=deepcopy(source);other.blocks.insert(1,block('Образец',3,'header'))
    other.blocks.append(block('Договор №123 | Стр. 3',3,'footer'))
    assert compare(source,other)==[]
    other.blocks.append(block('Изменённый заголовок',3,'header'))
    assert any('Изменённый' in c.after for c in compare(source,other))


def test_wrong_page_number_and_requisite_are_not_discarded():
    source=document([block('1. Условие.'),block('Договор №123 | Стр. 1',1,'footer'),block('Договор №123 | Стр. 2',2,'footer')])
    other=deepcopy(source);other.blocks[-1].text='Договор №124 | Стр. 9'
    changes=compare(source,other)
    assert changes and any('9' in c.after or '124' in c.after for c in changes)


@pytest.fixture(scope='module')
def pdf_pair():
    root=Path(__file__).resolve().parents[1]/'Тестовые файлы'
    if not (root/'new_generated_v2.pdf').exists():pytest.skip('Local regression PDF files absent')
    def load(name):return Document(name,'pdf','',pdf_content(root/name)[0],7,[],str(root/name),{})
    return load('Договор_исходный.pdf'),load('new_generated_v2.pdf')


def test_user_pdf_pair_has_whole_moves_and_no_furniture_changes(pdf_pair):
    old,new=pdf_pair;changes=compare(old,new)
    assert compare(old,old)==[] and compare(new,new)==[]
    assert len(changes)==24
    moves=[c for c in changes if c.operation=='move']
    assert len(moves)==4 and sum(bool(c.details.get('renumbered')) for c in moves)==3
    assert not any('УЧЕБНЫЙ ОБРАЗЕЦ' in c.before+c.after or 'Стр.' in c.before+c.after for c in changes)
    assert any(c.operation=='insert' and c.after.strip()=='по имеющимся у Продавца сведениям' for c in changes)
    assert sum(c.operation=='row_move' for c in changes)==1
    assert sum(c.operation=='row_insert' for c in changes)==1


@pytest.mark.parametrize('before,after',[('9 780 000','8 780 000'),('не входят','входят'),('0,03','0,003'),
                                        ('sales@granline-example.test','sales@other.test'),('6671196842','6671196843')])
def test_pdf_value_edits_are_not_lost(pdf_pair,before,after):
    old=deepcopy(pdf_pair[0]);new=deepcopy(old)
    def leaves(blocks):
        for b in blocks:
            if b.kind=='table':yield from (c for row in b.rows for c in row)
            else:yield b
    target=next(b for b in leaves(new.blocks) if before in b.text)
    target.text=target.text.replace(before,after,1)
    assert compare(old,new)
