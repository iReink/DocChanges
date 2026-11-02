"""DOCX logical structure + PDF character geometry. No OCR and no macro execution."""
import hashlib
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path
from difflib import SequenceMatcher
from lxml import etree
import pdfplumber
from shared.schema import Block, Document, Location
from shared.settings import ROOT, settings

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W = '{' + NS['w'] + '}'

def soffice_path():
    explicit = os.getenv('ATLAS_SOFFICE')
    if explicit and Path(explicit).is_file():
        return explicit
    for pattern in ('runtime/libreoffice/**/soffice.com', 'runtime/libreoffice/**/soffice.exe'):
        found = list(ROOT.glob(pattern))
        if found:
            return str(found[0])
    return None

def convert(path: Path, target: str, folder: Path):
    exe = soffice_path()
    if not exe:
        raise ValueError('Конвертер LibreOffice отсутствует. Запустите start_comparison.bat для установки.')
    folder.mkdir(parents=True, exist_ok=True)
    pipe=os.getenv('ATLAS_UNO_PIPE')
    python=ROOT/'runtime/libreoffice/App/libreoffice/program/python.exe'
    # Legacy DOC -> DOCX retains the verified CLI path. The persistent UNO
    # instance accelerates page rendering, where repeated startup dominated time.
    if pipe and python.is_file() and target.split(':')[0]=='pdf':
        output=folder/(path.stem+'.'+target.split(':')[0])
        filters={'pdf':'writer_pdf_Export','docx':'Office Open XML Text','doc':'MS Word 97'}
        filter_name=target.split(':',1)[1] if ':' in target else filters[target]
        command=[str(python),str(ROOT/'scripts/uno_convert.py'),'--pipe',pipe,'--input',str(path),
                 '--output',str(output),'--filter',filter_name]
        try:
            completed=subprocess.run(command,cwd=ROOT,capture_output=True,timeout=90,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            if completed.returncode==0 and output.is_file():return output
            raise ValueError('Конвертер не смог преобразовать документ. Перезапустите сервер сравнения и проверьте файл.')
        except subprocess.TimeoutExpired:raise ValueError('Превышено время преобразования документа (90 секунд).')
    profile = folder / ('profile-' + uuid.uuid4().hex)
    command = [exe, '-env:UserInstallation=' + profile.as_uri(), '--headless', '--nologo',
               '--nodefault', '--norestore', '--convert-to', target, '--outdir', str(folder), str(path)]
    creation = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        result = subprocess.run(command, capture_output=True, timeout=90, creationflags=creation)
        output = folder / (path.stem + '.' + target.split(':')[0])
        if result.returncode or not output.is_file():
            raise ValueError('LibreOffice не смог преобразовать документ. Проверьте файл и его формат.')
        return output
    except subprocess.TimeoutExpired:
        raise ValueError('Превышено время преобразования документа (90 секунд).')
    finally:
        shutil.rmtree(profile, ignore_errors=True)

def paragraph_text(node):
    parts = []
    for item in node.iter():
        if item.tag == W + 't':
            parts.append(item.text or '')
        elif item.tag in (W + 'br', W + 'cr'):
            parts.append('\n')
        elif item.tag == W + 'tab':
            parts.append('\t')
        elif item.tag == W + 'noBreakHyphen':
            parts.append('\u2011')
    return ''.join(parts)

class Numbering:
    def __init__(self, archive):
        self.nums, self.levels, self.counts = {}, {}, {}
        if 'word/numbering.xml' not in archive.namelist():
            return
        tree = etree.fromstring(archive.read('word/numbering.xml'))
        for node in tree.findall('w:num', NS):
            child = node.find('w:abstractNumId', NS)
            if child is not None:
                self.nums[node.get(W+'numId')] = child.get(W+'val')
        for abstract in tree.findall('w:abstractNum', NS):
            for level in abstract.findall('w:lvl', NS):
                def val(name, default):
                    el = level.find('w:'+name, NS)
                    return el.get(W+'val', default) if el is not None else default
                self.levels[(abstract.get(W+'abstractNumId'), int(level.get(W+'ilvl')))] = (
                    val('lvlText', '%1.'), val('numFmt', 'decimal'), int(val('start', '1')))
        self.styles = {}
        if 'word/styles.xml' in archive.namelist():
            styles = etree.fromstring(archive.read('word/styles.xml'))
            for style in styles.findall('w:style', NS):
                props = style.find('w:pPr/w:numPr', NS)
                if props is not None:
                    self.styles[style.get(W+'styleId')] = props

    def prefix(self, paragraph):
        props = paragraph.find('w:pPr/w:numPr', NS)
        if props is None:
            style = paragraph.find('w:pPr/w:pStyle', NS)
            if style is not None:
                props = getattr(self, 'styles', {}).get(style.get(W+'val'))
        if props is None:
            return ''
        number = props.find('w:numId', NS)
        if number is None:
            return ''
        num = number.get(W+'val')
        if num=='0':return ''
        level = props.find('w:ilvl', NS)
        lvl = int(level.get(W+'val')) if level is not None else 0
        abstract = self.nums.get(num)
        pattern, fmt, start = self.levels.get((abstract, lvl), ('%1.', 'decimal', 1))
        if not pattern:return ''
        if fmt == 'bullet':
            return '• '
        self.counts[(num, lvl)] = self.counts.get((num, lvl), start-1) + 1
        for key in list(self.counts):
            if key[0] == num and key[1] > lvl:
                del self.counts[key]
        def formatted(value,format_name):
            if format_name in ('lowerLetter','upperLetter'):
                letters=''
                while value:value,rem=divmod(value-1,26);letters=chr(65+rem)+letters
                return letters.lower() if format_name=='lowerLetter' else letters
            if format_name in ('lowerRoman','upperRoman'):
                roman=''
                for amount,token in [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]:
                    while value>=amount:roman+=token;value-=amount
                return roman.lower() if format_name=='lowerRoman' else roman
            return str(value)
        for i in range(lvl+1):
            level_fmt=self.levels.get((abstract,i),('',fmt,1))[1]
            pattern = pattern.replace('%'+str(i+1),formatted(self.counts.get((num,i),1),level_fmt))
        return pattern + ' '

def read_docx(path):
    blocks, warnings = [], []
    with zipfile.ZipFile(path) as archive:
        numbering = Numbering(archive)
        if 'word/numbering.xml' in archive.namelist() and etree.fromstring(archive.read('word/numbering.xml')).find('.//w:lvlOverride',NS) is not None:
            warnings.append('Индивидуальные переопределения нумерации Word требуют ручной проверки.')
        for name in archive.namelist():
            if name.startswith('word/') and name.endswith('.xml'):
                xml = etree.fromstring(archive.read(name))
                if xml.xpath('//w:ins | //w:del | //w:moveFrom | //w:moveTo', namespaces=NS):
                    raise ValueError('В Word есть неразрешённые исправления. Предоставьте финальную копию без исправлений.')
        relevant = ['word/document.xml'] + sorted(n for n in archive.namelist() if
                    re.match(r'word/(header\d+|footer\d+|footnotes|endnotes)\.xml$', n))
        counter = 0
        def parse(container, area):
            nonlocal counter
            result = []
            for node in container:
                if node.tag == W+'p':
                    counter += 1
                    text = numbering.prefix(node) + paragraph_text(node)
                    fields = ' '.join(node.xpath('.//w:instrText/text() | .//w:fldSimple/@w:instr', namespaces=NS))
                    result.append(Block(uuid.uuid4().hex, 'paragraph', text, counter, area=area,
                                        dynamic_fields=re.findall(r'\b(?:PAGE|NUMPAGES)\b', fields)))
                elif node.tag == W+'tbl':
                    rows, spans = [], []
                    for ri, row in enumerate(node.findall('w:tr', NS)):
                        cells = []
                        col = 0
                        for cell in row.findall('w:tc', NS):
                            counter += 1
                            texts = [paragraph_text(p) for p in cell.findall('w:p', NS)]
                            cells.append(Block(uuid.uuid4().hex, 'cell', '\n'.join(texts), counter, area=area))
                            span = cell.find('w:tcPr/w:gridSpan', NS)
                            merge = cell.find('w:tcPr/w:vMerge', NS)
                            width = int(span.get(W+'val')) if span is not None else 1
                            spans.append([ri, col, width, 0 if merge is None else (1 if merge.get(W+'val') == 'restart' else 2)])
                            col += width
                            if cell.find('w:tbl', NS) is not None:
                                warnings.append('Вложенная таблица требует ручной проверки.')
                        rows.append(cells)
                    result.append(Block(uuid.uuid4().hex, 'table', '\n'.join(' | '.join(c.text for c in r) for r in rows),
                                        rows=rows, spans=spans, area=area))
                elif node.tag in (W+'sdt', W+'sdtContent', W+'footnote', W+'endnote'):
                    if node.tag in (W+'footnote', W+'endnote') and int(node.get(W+'id','0')) < 1:
                        continue
                    result.extend(parse(node, area))
            return result
        for name in relevant:
            tree = etree.fromstring(archive.read(name))
            root = tree.find('w:body', NS) if name == 'word/document.xml' else tree
            blocks.extend(parse(root, 'body' if name=='word/document.xml' else name.split('/')[-1]))
            if tree.xpath('//w:drawing | //w:pict | //w:object | //w:txbxContent | //w:altChunk', namespaces=NS):
                warnings.append('Изображения, текстовые поля или встроенные объекты Word не проверены полностью.')
            if tree.xpath('//w:lvlOverride', namespaces=NS):
                warnings.append('Нестандартная нумерация требует ручной проверки.')
        if any(n.startswith('_xmlsignatures/') for n in archive.namelist()):
            warnings.append('Встроенная подпись Word обнаружена; её проверка не поддерживается.')
    return blocks, warnings

def pdf_content(path):
    blocks, warnings, page_data = [], [], []
    try:
        pdf = pdfplumber.open(path)
    except Exception as exc:
        raise ValueError('Не удалось открыть PDF. Возможно, файл повреждён или зашифрован.') from exc
    with pdf:
        if len(pdf.pages) > settings()['max_pages']:
            raise ValueError('Превышено ограничение количества страниц.')
        counter = 0
        for pi, page in enumerate(pdf.pages, 1):
            chars = page.chars
            page_data.append(chars)
            if not chars:
                warnings.append(f'Страница {pi}: нет доступного текста; OCR выключен.')
            if any('\ufffd' in c['text'] or '(cid:' in c['text'] for c in chars):
                warnings.append(f'Страница {pi}: часть символов не удалось надёжно декодировать.')
            if page.images:
                warnings.append(f'Страница {pi}: изображения не проверены на текст и изменения.')
            tables = page.find_tables()
            table_boxes = [t.bbox for t in tables]
            for table in tables:
                rows = []
                for row in table.rows:
                    cells = []
                    for bbox in row.cells:
                        counter += 1
                        text = page.crop(bbox).extract_text() or '' if bbox else ''
                        locs = [Location(pi,list(bbox),0,len(text),'cell')] if bbox else []
                        cells.append(Block(uuid.uuid4().hex, 'cell', text, counter, locs))
                    rows.append(cells)
                text = '\n'.join(' | '.join(c.text for c in row) for row in rows)
                blocks.append(Block(uuid.uuid4().hex, 'table', text, locations=[Location(pi,list(table.bbox),precision='table')], rows=rows))
            outside = page.filter(lambda obj: obj.get('object_type') != 'char' or not any(
                x0 <= (obj['x0']+obj['x1'])/2 <= x1 and y0 <= (obj['top']+obj['bottom'])/2 <= y1
                for x0,y0,x1,y1 in table_boxes))
            # PDF paragraphs are geometry-derived; line groups use vertical spacing and indentation.
            lines = outside.extract_text_lines(layout=False, return_chars=True)
            groups = []
            for line in lines:
                if groups:
                    prev = groups[-1][-1]
                    gap = line['top'] - prev['bottom']
                    height = max(prev['bottom']-prev['top'], 1)
                    # A first-line indent is not a paragraph boundary. A new
                    # numbered clause is, even when line spacing is unchanged.
                    same_indent = abs(line['x0']-prev['x0']) < 40
                    numbered = re.match(r'^\d+(?:\.\d+)*\.\s', line['text'])
                    if -.5 <= gap < height * .65 and same_indent and not numbered:
                        groups[-1].append(line)
                        continue
                groups.append([line])
            for group in groups:
                counter += 1
                text, locs = '', []
                for li, line in enumerate(group):
                    if li:
                        text += ' '
                    line_text = line['text']
                    start = len(text)
                    text += line_text
                    locs.append(Location(pi, [line['x0'],line['top'],line['x1'],line['bottom']], start,len(text),'line'))
                area = 'header' if group[-1]['bottom'] < page.height*.07 else 'footer' if group[0]['top'] > page.height*.94 else 'body'
                blocks.append(Block(uuid.uuid4().hex,'paragraph',text,counter,locs,area=area))
            # Preserve physical ordering, including tables.
        blocks.sort(key=lambda b: (b.locations[0].page, b.locations[0].bbox[1]) if b.locations else (0,0))
        pages = len(pdf.pages)
    warnings.append('Абзацы и таблицы PDF восстановлены по геометрии; сложная структура требует ручной проверки.')
    return blocks, warnings, pages, page_data

def flatten(blocks):
    for block in blocks:
        if block.kind == 'table':
            for row in block.rows:
                yield from row
        else:
            yield block

def attach_geometry(blocks, page_data):
    stream, locs = [], []
    for pi, chars in enumerate(page_data,1):
        for c in chars:
            for letter in c['text']:
                if not letter.isspace():
                    stream.append(letter)
                    locs.append((pi,[c['x0'],c['top'],c['x1'],c['bottom']]))
    text = ''.join(stream)
    cursor = 0
    missing = 0
    for block in flatten(blocks):
        target = ''.join(c for c in block.text if not c.isspace())
        if not target:
            continue
        pos = text.find(target, cursor)
        if pos < 0:
            pos = text.find(target)
        if pos >= 0:
            indices = [i for i,c in enumerate(block.text) if not c.isspace()]
            block.locations = [Location(locs[pos+j][0],locs[pos+j][1],idx,idx+1) for j,idx in enumerate(indices)]
            cursor = pos+len(target)
        else:
            # A paragraph can cross a page boundary. Headers/footers are present
            # in the PDF stream between its two parts, so a contiguous find fails.
            # Accept only a complete monotone match with gaps across pages.
            anchor=-1
            for length in (40,24,12,8):
                prefix=target[:min(length,len(target))]
                anchor=text.find(prefix,cursor)
                if anchor<0:anchor=text.find(prefix)
                if anchor>=0:break
            matched=[]
            if anchor>=0:
                window=text[anchor:anchor+len(target)+1500]
                runs=[r for r in SequenceMatcher(None,target,window,autojunk=False).get_matching_blocks() if r.size]
                complete=sum(r.size for r in runs)==len(target)
                safe=all(locs[anchor+x.b+x.size-1][0]!=locs[anchor+y.b][0]
                         for x,y in zip(runs,runs[1:]) if x.b+x.size<y.b)
                if complete and safe:
                    matched=[anchor+r.b+j for r in runs for j in range(r.size)]
            if matched:
                indices=[i for i,c in enumerate(block.text) if not c.isspace()]
                block.locations=[Location(locs[p][0],locs[p][1],idx,idx+1) for idx,p in zip(indices,matched)]
                cursor=matched[-1]+1
            else:missing += 1
    for block in blocks:
        if block.kind == 'table':
            block.locations = [loc for row in block.rows for cell in row for loc in cell.locations]
    return missing

def extract(path: Path, name: str, folder: Path,structure_only=False):
    ext = Path(name).suffix.lower().lstrip('.')
    data = path.read_bytes()
    if ext not in ('doc','docx','pdf'):
        raise ValueError('Поддерживаются DOC, DOCX и PDF.')
    if ext == 'pdf' and not data.startswith(b'%PDF-'):
        raise ValueError('Содержимое файла не соответствует PDF.')
    if ext == 'doc' and not data.startswith(bytes.fromhex('D0CF11E0A1B11AE1')):
        raise ValueError('Содержимое файла не соответствует старому формату DOC.')
    if ext == 'docx' and not zipfile.is_zipfile(path):
        raise ValueError('Содержимое файла не соответствует DOCX.')
    if ext == 'pdf':
        preview = folder / 'preview.pdf'
        shutil.copyfile(path, preview)
        blocks,warnings,pages,pdf_chars = pdf_content(preview)
    else:
        source=folder/'docx'/(path.stem+'.docx') if ext=='doc' else path
        if ext=='doc' and not source.exists():source=convert(path,'docx',folder/'docx')
        blocks,warnings = read_docx(source)
        if structure_only:
            coverage={'text':'partial' if warnings else 'complete','tables':'complete',
                      'formatting':'paragraphs_and_breaks','navigation':'pending','signatures':'not_checked'}
            return Document(name,ext,hashlib.sha256(data).hexdigest(),blocks,0,warnings,str(folder/'preview.pdf'),coverage)
        converted = convert(source,'pdf:writer_pdf_Export',folder/'render')
        preview = folder/'preview.pdf'
        shutil.copyfile(converted,preview)
        # Word already supplies structure: avoid re-detecting PDF tables and
        # paragraphs just to obtain glyph coordinates.
        with pdfplumber.open(preview) as pdf:
            pages=len(pdf.pages)
            if pages>settings()['max_pages']:raise ValueError('Превышено ограничение количества страниц.')
            geometry=[page.chars for page in pdf.pages]
        content_incomplete=bool(warnings)
        missing = attach_geometry(blocks,geometry)
        if missing:
            warnings.append(f'Не удалось точно привязать к страницам {missing} текстовых блоков Word.')
        if ext == 'doc':
            warnings.append('DOC преобразован в DOCX; возможны особенности структуры и вёрстки.')
    pdf_text_status = ('unavailable' if not any(pdf_chars) else 'partial' if any(not chars for chars in pdf_chars) or any('декодировать' in w for w in warnings) else 'complete') if ext=='pdf' else None
    coverage = {'text':pdf_text_status if ext=='pdf' else ('partial' if content_incomplete else 'complete'),
                'tables':'reconstructed' if ext=='pdf' else 'complete',
                'formatting':'not_applicable' if ext=='pdf' else 'paragraphs_and_breaks',
                'navigation':'partial' if any(not b.locations and b.text.strip() for b in flatten(blocks)) else 'complete',
                'signatures':'not_checked'}
    return Document(name,ext,hashlib.sha256(data).hexdigest(),blocks,pages,list(dict.fromkeys(warnings)),str(preview),coverage)
