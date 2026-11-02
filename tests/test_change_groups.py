from comparison_server.diff import text_changes
from shared.schema import Block


def edits(old,new,table=False):
    return text_changes(Block('a','cell' if table else 'paragraph',old),Block('b','cell' if table else 'paragraph',new),table=table)


def rebuild(old,changes):
    fragments=sorted([f for c in changes for f in c.details['fragments']],key=lambda f:f['old_range'])
    result='';cursor=0
    for f in fragments:
        lo,hi=f['old_range'];assert old[lo:hi]==f['before']
        result+=old[cursor:lo]+f['after'];cursor=hi
    return result+old[cursor:]


def test_amount_written_once():
    old='Цена 9 780 000 (Девять миллионов семьсот восемьдесят тысяч) рублей.'
    new='Цена 8 780 000 (Восемь миллионов семьсот восемьдесят тысяч) рублей.'
    changes=edits(old,new)
    assert len(changes)==1 and changes[0].categories==['money']
    assert 'Девять' in changes[0].details['display_before'] and 'Восемь' in changes[0].details['display_after']
    assert rebuild(old,changes)==new


def test_amount_and_deadline_separate_same_sentence():
    old='Открыть на сумму 100 рублей не позднее 5 (Пяти) рабочих дней.'
    new='Открыть на сумму 200 рублей не позднее 15 (Пятнадцати) рабочих дней.'
    changes=edits(old,new)
    assert len(changes)==2 and {c.details['grouping'] for c in changes}=={'field'}
    assert rebuild(old,changes)==new
    assert changes[1].details['display_before']=='5 (Пяти) рабочих дней'


def test_duration_words_and_endings_one():
    old='Подтвердить в течение 3 (Трех) рабочих дней.'
    new='Подтвердить в течение 1 (Одного) рабочего дня.'
    changes=edits(old,new)
    assert len(changes)==1 and changes[0].categories==['dates']
    assert rebuild(old,changes)==new


def test_rates_character_ranges_and_full_values():
    for old,new in [('0,03 %','0,003 %'),('0,03 %','0,3 %'),('3 %','30 %')]:
        changes=edits('Неустойка '+old,'Неустойка '+new)
        assert len(changes)==1 and changes[0].categories==['money']
        assert changes[0].details['display_before']==old and changes[0].details['display_after']==new
        assert rebuild('Неустойка '+old,changes)=='Неустойка '+new
        fragment=changes[0].details['fragments'][0]
        assert len(fragment['before']+fragment['after'])==1


def test_two_rates_are_two_changes():
    changes=edits('Неустойка 0,03 %, но не более 3 %.','Неустойка 0,3 %, но не более 30 %.')
    assert len(changes)==2


def test_email_one_requisite_inside_table():
    old='Эл. почта: sales@company-example.test\nТелефон: 123'
    new='Эл. почта: buyer.new@example.test\nТелефон: 123'
    changes=edits(old,new,True)
    assert len(changes)==1 and set(changes[0].categories)=={'table','requisites'}
    assert changes[0].details['display_before']=='sales@company-example.test'
    assert rebuild(old,changes)==new


def test_negation_does_not_include_following_word():
    old='Оборудование не входит в цену.';new='Оборудование входит в цену.'
    changes=edits(old,new)
    assert len(changes)==1 and changes[0].details['display_before']=='не'
    assert changes[0].details['fragments'][0]['before'].strip()=='не'
    assert rebuild(old,changes)==new


def test_one_clause_with_multiple_rephrasings():
    old='Риск до передачи несет Продавец, после передачи — Покупатель.'
    new='Риск до истечения 30 дней после передачи несет Продавец, по истечении срока — Покупатель.'
    changes=edits(old,new)
    assert len(changes)==1 and rebuild(old,changes)==new
