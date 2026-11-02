"""Artificial contracts, no real company data. Run with comparison environment."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from docx import Document
from docx.shared import Pt
from shared.settings import ROOT

def create(folder=None):
    folder=folder or ROOT/'tests/fixtures';folder.mkdir(parents=True,exist_ok=True)
    for variant in ('old','new'):
        doc=Document();doc.styles['Normal'].font.name='Arial';doc.styles['Normal'].font.size=Pt(11)
        doc.add_heading('Договор поставки № 42',0)
        doc.add_paragraph('г. Екатеринбург                                      30 октября 2026 года')
        doc.add_paragraph('ООО «Пример Заказчик», именуемое «Заказчик», и ООО «Пример Поставщик», именуемое «Поставщик», заключили настоящий договор.')
        doc.add_heading('1. Предмет договора',1)
        doc.add_paragraph('Поставщик обязуется поставить материалы, а Заказчик — принять и оплатить их.')
        doc.add_heading('2. Стоимость и сроки',1)
        doc.add_paragraph('Общая стоимость поставки составляет '+('500 000' if variant=='old' else '650 000')+' рублей.')
        doc.add_paragraph('Срок поставки составляет 10 '+('рабочих' if variant=='old' else 'календарных')+' дней с момента оплаты.')
        doc.add_heading('3. Спецификация',1)
        table=doc.add_table(rows=1,cols=4);table.style='Table Grid'
        for cell,text in zip(table.rows[0].cells,['Код','Материал','Количество','Цена, руб.']):cell.text=text
        rows=[['А-01','Кирпич','100','100'],['А-02','Бетон','20','200']]
        if variant=='new':rows[0][3]='120';rows.insert(1,['А-03','Песок','5','50'])
        for row in rows:
            for cell,text in zip(table.add_row().cells,row):cell.text=text
        doc.add_heading('4. Реквизиты сторон',1)
        doc.add_paragraph('Заказчик: ООО «Пример Заказчик». ИНН '+('7701234567' if variant=='old' else '7701234568')+'.')
        doc.add_paragraph('Поставщик: ООО «Пример Поставщик». ИНН 7709876543.')
        doc.add_paragraph('Все сведения и реквизиты в этом документе искусственные и предназначены для демонстрации.')
        doc.save(folder/(variant+'.docx'))
    (folder/'expected.json').write_text(json.dumps({'description':'Искусственные договоры','expected_types':['money','dates','requisites','table'],'expected_row_insertions':1},ensure_ascii=False,indent=2),encoding='utf-8')
    return folder

if __name__=='__main__':print(create())
