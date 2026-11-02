from comparison_server.diff import compare, text_changes, party_name_spans
from shared.schema import Block, Document, Location


def paragraph(text,index):
    return Block(str(index),'paragraph',text,index,[Location(index,[0,0,100,20],0,len(text))])


def doc(blocks):return Document('test.docx','docx','hash',blocks,1,[],'',{})


def table(rows):
    cells=[[paragraph(value,i*10+j+1) for j,value in enumerate(row)] for i,row in enumerate(rows)]
    for row in cells:
        for cell in row:cell.kind='cell'
    return Block('table','table','\n'.join(' | '.join(row) for row in rows),rows=cells)


def reconstruct(old,changes):
    result='';cursor=0
    fragments=sorted((f for c in changes for f in c.details.get('fragments',[])),key=lambda f:f['old_range'])
    for f in fragments:
        lo,hi=f['old_range'];assert lo>=cursor and old[lo:hi]==f['before']
        result+=old[cursor:lo]+f['after'];cursor=hi
    return result+old[cursor:]


def test_moved_numbered_clause_retains_number_change_and_locations():
    a=[paragraph('2.6. Особое условие регистрации.',1),paragraph('Следующий раздел без изменений.',2)]
    b=[paragraph(a[1].text,1),paragraph('3.5. Особое условие регистрации.',2)]
    changes=compare(doc(a),doc(b))
    assert len(changes)==1 and changes[0].operation=='move'
    c=changes[0];assert c.details['renumbered']
    assert c.old_locations[0].page==1 and c.new_locations[0].page==2
    assert reconstruct(a[0].text,changes)==b[1].text


def test_renumber_in_place_is_edit_not_move():
    changes=compare(doc([paragraph('2.6. Особое условие регистрации.',1)]),doc([paragraph('3.5. Особое условие регистрации.',1)]))
    assert changes and all(c.operation!='move' for c in changes)


def test_move_with_line_break_edit_does_not_claim_renumbering():
    old=paragraph('2.6. Особое условие\nрегистрации.',1)
    anchor=paragraph('Следующий раздел без изменений.',2)
    new=paragraph('2.6. Особое условие регистрации.',2)
    changes=compare(doc([old,anchor]),doc([anchor,new]))
    assert len(changes)==1 and changes[0].operation=='move'
    assert not changes[0].details['renumbered'] and 'formatting' in changes[0].categories
    assert reconstruct(old.text,changes)==new.text


def test_sentence_move_one_parent_without_numbering_leak():
    old='1.3. Квартира находится в доме. Разрешение выдано вчера. Предметом является квартира.'
    new='1.3. Предметом является квартира. Квартира находится в доме. Разрешение выдано вчера.'
    changes=text_changes(paragraph(old,1),paragraph(new,1))
    assert len(changes)==1 and changes[0].operation=='move'
    assert changes[0].before=='Предметом является квартира.'
    assert reconstruct(old,changes)==new


def test_semantically_similar_rephrasing_is_not_move():
    old='1.3. Покупатель обязан оплатить квартиру. Передача происходит завтра.'
    new='1.3. Передача происходит завтра. Покупатель вправе оплатить квартиру.'
    changes=text_changes(paragraph(old,1),paragraph(new,1))
    assert changes and all(c.operation!='move' for c in changes)
    assert reconstruct(old,changes)==new


def test_row_move_and_genuine_insertion_separate():
    a=table([['Комната','Площадь'],['Комната А','18'],['Комната Б','12'],['Кухня','10']])
    b=table([['Комната','Площадь'],['Комната Б','12'],['Комната А','18'],['Кухня','10'],['Лоджия','3']])
    changes=compare(doc([a]),doc([b]))
    assert sorted(c.operation for c in changes)==['row_insert','row_move']
    moved=next(c for c in changes if c.operation=='row_move')
    assert moved.before==moved.after and moved.old_locations and moved.new_locations


def test_insertion_above_rows_does_not_move_every_row():
    a=table([['Код','Цена'],['А','100'],['Б','200']])
    b=table([['Код','Цена'],['В','300'],['А','100'],['Б','200']])
    changes=compare(doc([a]),doc([b]))
    assert len(changes)==1 and changes[0].operation=='row_insert'


def test_row_keeps_identity_when_moved_and_edited():
    a=table([['Комната','Площадь'],['Комната А','16,4'],['Комната Б','12,1'],['Кухня','10']])
    b=table([['Комната','Площадь'],['Комната Б','12,1'],['Комната А','18,4'],['Кухня','10']])
    for old,new in [(a,b),(b,a)]:
        changes=compare(doc([old]),doc([new]))
        assert len(changes)==1 and changes[0].operation=='row_move'
        assert changes[0].details['edited'] and changes[0].details['identity_key']=='Комната А'
        assert changes[0].details['cell_changes'] and changes[0].before!=changes[0].after


def test_changed_key_is_not_proof_of_same_row():
    a=table([['Код','Сумма'],['А','100'],['Б','200']])
    b=table([['Код','Сумма'],['Б','200'],['В','900']])
    changes=compare(doc([a]),doc([b]))
    assert not any(c.operation=='row_move' and c.details.get('edited') for c in changes)


def test_connected_condition_with_semicolon_is_one_group():
    old='Комиссии банка оплачивает Покупатель, если иное не предусмотрено тарифами банка.'
    new='Комиссии первоначально оплачивает Покупатель; Продавец возмещает их после передачи.'
    changes=text_changes(paragraph(old,1),paragraph(new,1))
    assert len(changes)==1 and reconstruct(old,changes)==new


def test_court_is_not_contractual_party():
    text='Покупатель передает спор суду Российской Федерации по месту нахождения Продавца.'
    assert not party_name_spans(text)
    assert party_name_spans('Продавец: ООО «Альфа»')
    assert party_name_spans('гражданин Российской Федерации Нестеров Максим Андреевич, именуемый Покупатель')


def test_party_name_change_but_not_quoted_contract_object():
    changes=text_changes(paragraph('Продавец — ООО «Альфа».',1),paragraph('Продавец — ООО «Бета».',1))
    assert len(changes)==1 and 'parties' in changes[0].categories
    changes=text_changes(paragraph('Покупатель получает «Квартиру».',1),paragraph('Покупатель получает «Дом».',1))
    assert all('parties' not in c.categories for c in changes)


def test_guarantee_start_event_and_debt_are_classified():
    old='Гарантийный срок составляет 12 месяцев с даты подписания передаточного акта.'
    new='Гарантийный срок составляет 12 месяцев с даты государственной регистрации перехода права.'
    assert all('dates' in c.categories for c in text_changes(paragraph(old,1),paragraph(new,1)))
    changes=text_changes(paragraph('Продавец обязан погасить задолженность.',1),paragraph('Продавец обязан предоставить сведения о задолженности.',1))
    assert all('money' in c.categories for c in changes)
