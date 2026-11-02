from shared.schema import Block,Document
from comparison_server.diff import compare

def doc(blocks,fmt='docx'):
    return Document('test.'+fmt,fmt,'hash',blocks,1,[],'',{})

def p(text):return Block(text,'paragraph',text)
def table(rows):
    values=[[Block(f'{i}:{j}','cell',v) for j,v in enumerate(row)] for i,row in enumerate(rows)]
    return Block('table','table','\n'.join(' | '.join(r) for r in rows),rows=values)

def test_identical():assert compare(doc([p('Текст')]),doc([p('Текст')]))==[]
def test_single_digit():
    edits=compare(doc([p('Стоимость: 500 000 рублей')]),doc([p('Стоимость: 650 000 рублей')]))
    assert len(edits)==1 and 'money' in edits[0].categories
def test_negation():
    edits=compare(doc([p('Заказчик вправе отказаться')]),doc([p('Заказчик не вправе отказаться')]))
    assert edits and 'не' in ''.join(c.after for c in edits)
def test_split_paragraph():
    edits=compare(doc([p('Первое предложение. Второе предложение.')]),doc([p('Первое предложение.'),p('Второе предложение.')]))
    assert len(edits)==1 and edits[0].operation=='paragraph_boundary'
def test_line_break():
    edits=compare(doc([p('Первое Второе')]),doc([p('Первое\nВторое')]))
    assert len(edits)==1 and edits[0].categories==['formatting']
def test_pdf_wrapping():assert not compare(doc([p('Текст\nстроки')],'pdf'),doc([p('Текст строки')],'pdf'))
def test_table_row_insert_one():
    a=table([['Код','Наименование','Цена'],['А1','Кирпич','100'],['А2','Бетон','200']])
    b=table([['Код','Наименование','Цена'],['А1','Кирпич','100'],['А3','Песок','50'],['А2','Бетон','200']])
    edits=compare(doc([a]),doc([b]));assert len(edits)==1 and edits[0].operation=='row_insert'
def test_existing_cell():
    a=table([['Код','Наименование','Цена'],['А1','Кирпич','100']]);b=table([['Код','Наименование','Цена'],['А1','Кирпич','120']])
    edits=compare(doc([a]),doc([b]));assert len(edits)==1 and 'money' in edits[0].categories and 'table' in edits[0].categories
def test_column_insert_one():
    a=table([['Код','Цена'],['А1','100'],['А2','200']]);b=table([['Код','Количество','Цена'],['А1','3','100'],['А2','4','200']])
    edits=compare(doc([a]),doc([b]));assert len(edits)==1 and edits[0].operation=='column_insert'
def test_requisites():
    edits=compare(doc([p('ИНН заказчика 7701234567')]),doc([p('ИНН заказчика 7701234568')]))
    assert len(edits)==1 and 'requisites' in edits[0].categories
def test_similar_unicode():
    assert compare(doc([p('Код A12')]),doc([p('Код А12')]))
def test_moved():
    a=[p('Первый пункт'),p('Совсем другой второй'),p('Третий пункт')]
    b=[a[1],a[0],a[2]]
    edits=compare(doc(a),doc(b));assert any(c.operation=='move' for c in edits)
def test_embedding_cannot_hide_change():
    a,b=doc([p('Цена 100 рублей')]),doc([p('Цена 900 рублей')])
    assert compare(a,b,{(0,0):1.0})
def test_long_suffix():
    a='условие '*600+'100 рублей';b='условие '*600+'200 рублей'
    assert compare(doc([p(a)]),doc([p(b)]))

def test_unchanged_requisite_does_not_label_changed_amount():
    edits=compare(doc([p('ИНН 7701234567. Стоимость 100 рублей.')]),doc([p('ИНН 7701234567. Стоимость 200 рублей.')]))
    assert len(edits)==1 and 'money' in edits[0].categories and 'requisites' not in edits[0].categories

def test_table_quantity_is_not_price():
    a=table([['Код','Количество','Цена'],['А1','10','100']]);b=table([['Код','Количество','Цена'],['А1','12','100']])
    edits=compare(doc([a]),doc([b]));assert len(edits)==1 and 'money' not in edits[0].categories

def test_cell_merge_grouping():
    a=table([['Код','Название','Цена'],['A','B','100']]);b=table([['Код','Название','Цена'],['A\nB','100']])
    a.spans=[[1,0,1,0],[1,1,1,0],[1,2,1,0]];b.spans=[[1,0,2,0],[1,2,1,0]]
    edits=compare(doc([a]),doc([b]));assert len(edits)==1 and edits[0].operation=='cell_merge'
