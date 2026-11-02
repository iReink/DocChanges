from copy import deepcopy
from pathlib import Path
import pytest
from comparison_server.diff import compare
from comparison_server.extract import read_docx, pdf_content
from shared.schema import Block, Document, Location


def test_page_line_splits_are_ignored_but_added_clause_survives():
    text='2.4. Стороны обязуются передать документы после получения оплаты в полном объеме.'
    word=Document('a.docx','docx','',[Block('a','paragraph',text)],0,[],'',{})
    pdf=Document('a.pdf','pdf','',[Block('b','paragraph',text[:40]),Block('c','paragraph',text[40:])],2,[],'',{})
    # Use a real word boundary rather than deleting a space inside a word.
    cut=text.index('после')
    pdf.blocks[0].text=text[:cut];pdf.blocks[1].text=text[cut:]
    assert compare(word,pdf)==[]
    pdf.blocks[1].text+=' От оплаты Покупатель освобожден.'
    assert any('освобожден' in c.after for c in compare(word,pdf))


def test_unknown_footer_text_is_not_silently_removed():
    word=Document('a.docx','docx','',[Block('a','paragraph','Согласованные условия договора.')],0,[],'',{})
    pdf=deepcopy(word);pdf.format='pdf'
    pdf.blocks.append(Block('extra','paragraph','Ответственность отменена.',area='footer'))
    assert any('Ответственность' in c.after for c in compare(word,pdf))


@pytest.fixture(scope='module')
def original_pair():
    root=Path(__file__).resolve().parents[1]/'Тестовые файлы'
    if not (root/'Договор_исходный.pdf').exists():
        pytest.skip('Local user-provided cross-format regression documents are absent')
    # Mixed inputs use independently extracted PDF views, including Word's own render.
    b,*_=pdf_content(root/'Договор_исходный.pdf')
    a=deepcopy(b)
    return (Document('old_generated.docx','docx','',a,0,[],'',{}),
            Document('Договор_исходный.pdf','pdf','',b,7,[],str(root/'Договор_исходный.pdf'),{}))


def test_identical_user_document_in_both_directions(original_pair):
    a,b=original_pair
    assert compare(a,b)==[]
    assert compare(b,a)==[]


@pytest.mark.parametrize('before,after',[
    ('9 780 000','8 780 000'),('не входят','входят'),
    ('0,03','0,003'),('sales@granline-example.test','sales@other-example.test'),
    ('6671196842','6671196843'),('Продавец','Покупатель'),
])
def test_real_edits_survive_cross_format_normalisation(original_pair,before,after):
    word,pdf=deepcopy(original_pair)
    def leaves(blocks):
        for block in blocks:
            if block.kind=='table':
                yield from (cell for row in block.rows for cell in row)
            else:yield block
    target=next(b for b in leaves(word.blocks) if before in b.text)
    target.text=target.text.replace(before,after,1)
    for table in word.blocks:
        if table.kind=='table':table.text='\n'.join(' | '.join(c.text for c in row) for row in table.rows)
    edits=compare(word,pdf)
    assert edits, (before,after)
    assert any(c.before!=c.after for c in edits)


def test_new_pdf_clause_is_not_discarded(original_pair):
    word,pdf=deepcopy(original_pair)
    block=next(b for b in pdf.blocks if '2.1.' in b.text and b.area=='body')
    block.text+=' Дополнительный штраф составляет 500 рублей.'
    assert any('штраф' in c.after or 'штраф' in c.before for c in compare(word,pdf))


def test_unsigned_pdf_with_non_strict_xref_is_not_a_signature(original_pair):
    from comparison_server.signatures import inspect_signatures
    assert inspect_signatures(Path(original_pair[1].preview),[],'pdf')==[]
