import json
from pathlib import Path
from html import escape
from docx import Document
from docx.shared import Pt, Inches
from docx.shared import Mm
from docx.enum.section import WD_ORIENT
from docx.oxml import OxmlElement
from docx.shared import RGBColor
from docx.oxml.ns import qn
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4,landscape
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle
from shared.settings import ROOT
from .diff import LABELS

OPERATIONS={'insert':'Добавлен текст','delete':'Удалён текст','replace':'Замена',
 'row_insert':'Добавлена строка','row_delete':'Удалена строка','row_move':'Перемещена строка','column_insert':'Добавлен столбец',
 'column_delete':'Удалён столбец','table_insert':'Добавлена таблица','table_delete':'Удалена таблица',
 'cell_merge':'Изменено объединение ячеек','paragraph_boundary':'Изменена граница абзаца','move':'Перемещение','signature_change':'Изменён состав подписей'}

def lines(result):
    yield 'Отчёт о сравнении документов'
    for side,label in [('old','Согласованная версия'),('new','Полученная версия')]:
        doc=result['documents'][side]
        yield f"{label}: {doc['name']} ({doc['format'].upper()})"
        yield 'SHA-256: '+doc['sha256']
    yield 'Результат: '+result['summary']
    yield 'Полнота: '+('Сравнение выполнено не полностью' if result['partial'] else 'Проверки согласованного объёма завершены')
    yield 'Привязка к страницам: '+('есть ограничения' if result.get('navigation_partial') else 'выполнена')
    yield 'Дата и время: '+result['compared_at']
    yield 'Сотрудник: '+result['employee']
    yield 'Общее количество изменений: '+('не определено — текст не проверен' if result.get('comparison_status')=='unavailable' else str(result['count']))
    for idx,c in enumerate(result['changes'],1):
        yield f"{idx}. {OPERATIONS.get(c['operation'],c['operation'])}: "+', '.join(LABELS.get(v,v) for v in c['categories'])
        for side,label in [('old','Было'),('new','Стало')]:
            pages=sorted({l['page'] for l in c[side+'_locations']})
            paragraph=c[side+'_paragraph']
            yield f"{label} (страницы: {', '.join(map(str,pages)) or 'не установлены'}; абзац/блок: {paragraph or 'не установлен'}):"
            field='before' if side=='old' else 'after'
            yield c.get('details',{}).get('display_'+field,c[field]) or '—'
        if c['confidence']!='exact':yield 'Сопоставление фрагментов предложено моделью; проверьте соответствие.'
    yield 'Электронные подписи'
    yield 'Доверие к сертификатам и отзыв не проверялись. Указанное время подписания не является подтверждённой меткой времени.'
    names={'valid':'Соответствует файлу','invalid':'Проверка не пройдена','not_checked':'Не проверено'}
    for side,label in [('old','Согласованная версия'),('new','Полученная версия')]:
        if not result['signatures'][side]:yield label+': подписи не предоставлены / не обнаружены.'
        for sig in result['signatures'][side]:
            yield label+': '+names.get(sig.get('mathematical'),'Не проверено')
            for field in ('subject','issuer','algorithm_name','not_before','not_after','claimed_signing_time','message'):
                if sig.get(field):
                    field_label={'subject':'Подписант','issuer':'Издатель сертификата','algorithm_name':'Алгоритм',
                           'not_before':'Действует с','not_after':'Действует до','claimed_signing_time':'Заявленное время подписания','message':'Сведения'}[field]
                    yield field_label+': '+str(sig[field])
    if result['warnings']:
        yield 'Ограничения проверки'
        for warning in result['warnings']:yield '• '+warning
    yield 'Страницы Word относятся к отображению комплекса. Абзацы PDF восстановлены по геометрии.'
    yield 'Версия алгоритма: '+result['algorithm_version']
    for role,model in result['models'].items():
        yield ('Сопоставление' if role=='embedding' else 'Извлечение сущностей')+': '+model['id']+'; ревизия: '+model['revision']


def report_rows(result):
    rows=[]
    for idx,c in enumerate(result['changes'],1):
        place=[]
        for side,label in [('old','Было'),('new','Стало')]:
            pages=sorted({l['page'] for l in c[side+'_locations']})
            value=c.get('details',{}).get('display_before' if side=='old' else 'display_after',c['before' if side=='old' else 'after'])
            location='стр. '+', '.join(map(str,pages)) if pages else ('не установлена' if value else '—')
            if c[side+'_paragraph']:location+='; абз./блок '+str(c[side+'_paragraph'])
            place.append(label+': '+location)
        kind=('Перемещение и перенумерация' if c.get('details',{}).get('renumbered') else OPERATIONS.get(c['operation'],c['operation']))+'\n'+', '.join(LABELS.get(v,v) for v in c['categories'])
        if c['operation']=='row_move' and c.get('details',{}).get('edited'):kind='Перемещение и изменение строки\n'+', '.join(LABELS.get(v,v) for v in c['categories'])
        if c['confidence']!='exact':kind+='\nПроверьте сопоставление'
        rows.append([str(idx),kind,c.get('details',{}).get('display_before',c['before']) or '—',
                     c.get('details',{}).get('display_after',c['after']) or '—','\n'.join(place)])
    return rows

def make_report(result,folder: Path,fmt):
    path=folder/('report.'+fmt)
    if path.is_file():return path
    if fmt=='json':
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return path
    content=list(lines(result))
    if result.get('comparison_status')=='unavailable':
        if fmt=='docx':
            doc=Document()
            for i,text in enumerate(content):doc.add_paragraph(text,style='Title' if i==0 else None)
            doc.save(path);return path
        font=ROOT/'vendor/fonts/NotoSans-Regular.ttf'
        if 'Atlas' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('Atlas',str(font)))
        style=ParagraphStyle('Unavailable',fontName='Atlas',fontSize=10,leading=14,spaceAfter=8)
        SimpleDocTemplate(str(path),pagesize=A4).build([Paragraph(escape(t),style) for t in content])
        return path
    # Keep one source for metadata/signatures while presenting changes as rows.
    first=next((i for i,t in enumerate(content) if t.startswith('1. ')),content.index('Электронные подписи'))
    tail=content.index('Электронные подписи')
    before,after=content[:first],content[tail:]
    headers=['№','Изменение и категория','Было','Стало','Местоположение']
    rows=report_rows(result)
    if fmt=='docx':
        doc=Document();normal=doc.styles['Normal'];normal.font.name='Arial';normal.font.size=Pt(10)
        normal.paragraph_format.space_after=Pt(5)
        for name in ('Title','Normal'):
            style=doc.styles[name];style.font.color.rgb=RGBColor(0,0,0);style.font.underline=False
            for border in list(style.element.iter(qn('w:pBdr'))):border.getparent().remove(border)
        doc.styles['Title'].font.size=Pt(20)
        section=doc.sections[0];section.orientation=WD_ORIENT.LANDSCAPE
        section.page_width=Mm(297);section.page_height=Mm(210)
        section.left_margin=section.right_margin=Mm(12);section.top_margin=section.bottom_margin=Mm(12)
        for i,text in enumerate(before):doc.add_paragraph(text,style='Title' if i==0 else None)
        doc.add_paragraph('Одна строка — одно сгруппированное изменение. Точные фрагменты доступны в интерфейсе и JSON.')
        table=doc.add_table(rows=1,cols=5);table.style='Table Grid';table.autofit=False
        widths=[9,40,78,78,68]
        for column,width in zip(table.columns,widths):column.width=Mm(width)
        for cell,text,width in zip(table.rows[0].cells,headers,widths):
            cell.width=Mm(width);cell.text=text
            shading=OxmlElement('w:shd');shading.set(qn('w:fill'),'214F44');cell._tc.get_or_add_tcPr().append(shading)
            for run in cell.paragraphs[0].runs:run.font.color.rgb=RGBColor(255,255,255);run.bold=True
        repeat=OxmlElement('w:tblHeader');table.rows[0]._tr.get_or_add_trPr().append(repeat)
        for row in rows:
            table_row=table.add_row()
            if max(map(len,row))<2000:
                table_row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
            for cell,text,width in zip(table_row.cells,row,widths):cell.width=Mm(width);cell.text=text
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.space_after=Pt(4)
                    for run in p.runs:run.font.size=Pt(9)
        doc.add_paragraph()
        for text in after:doc.add_paragraph(text)
        doc.save(path);return path
    font=ROOT/'vendor/fonts/NotoSans-Regular.ttf'
    if not font.exists():raise ValueError('Не найден кириллический шрифт. Повторите установку.')
    if 'Atlas' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('Atlas',str(font)))
    style=ParagraphStyle('AtlasBody',fontName='Atlas',fontSize=9,leading=13,spaceAfter=7,wordWrap='CJK')
    title=ParagraphStyle('AtlasTitle',parent=style,fontSize=17,leading=23,spaceAfter=18)
    story=[Paragraph(escape(t),title if i==0 else style) for i,t in enumerate(before)]
    story.append(Paragraph('Одна строка — одно сгруппированное изменение. Точные фрагменты доступны в интерфейсе и JSON.',style))
    cell_style=ParagraphStyle('Cell',parent=style,fontSize=8,leading=11,spaceAfter=0)
    head_style=ParagraphStyle('Head',parent=cell_style,textColor=colors.white)
    data=[[Paragraph(escape(t),head_style) for t in headers]]
    data.extend([[Paragraph(escape(t).replace('\n','<br/>'),cell_style) for t in row] for row in rows])
    table=LongTable(data,colWidths=[25,110,215,215,205],repeatRows=1,splitByRow=1,splitInRow=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#214f44')),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f1f5f3')]),
        ('GRID',(0,0),(-1,-1),.4,colors.HexColor('#cad6cf')),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
        ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    story.extend([table,Spacer(1,16)])
    story.extend(Paragraph(escape(t).replace('\n','<br/>'),style) for t in after)
    def footer(canvas,document):
        canvas.setFont('Atlas',8);canvas.drawRightString(805,20,str(document.page))
    SimpleDocTemplate(str(path),pagesize=landscape(A4),leftMargin=36,rightMargin=36,topMargin=30,bottomMargin=30).build(story,onFirstPage=footer,onLaterPages=footer)
    return path
