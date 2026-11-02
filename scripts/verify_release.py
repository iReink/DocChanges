"""Check the running suite and render its final reports for visual inspection."""
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from comparison_server.extract import convert


def main():
    target = ROOT / 'work/final-qa'
    target.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url='http://localhost:8000', timeout=180) as client:
        with (ROOT / 'tests/fixtures/old.docx').open('rb') as old, (ROOT / 'tests/fixtures/new.docx').open('rb') as new:
            response = client.post('/api/v1/comparisons', data={'employee': 'Тестовый сотрудник'},
                                   files={'old': ('Согласованная версия.docx', old), 'new': ('Полученная версия.docx', new)})
        response.raise_for_status()
        jid = response.json()['id']
        print('Задача: ' + jid, flush=True)
        for _ in range(450):
            state = client.get(f'/api/v1/comparisons/{jid}').json()
            if state['state'] not in ('queued', 'running'):
                break
            time.sleep(2)
        assert state['state'] == 'completed', state
        result = client.get(f'/api/v1/comparisons/{jid}/result').json()
        assert result['count'] == 5 and result['ai_state'] == 'used', result
        assert not result['warnings'], result['warnings']
        for fmt in ('pdf', 'docx', 'json'):
            report = client.get(f'/api/v1/comparisons/{jid}/reports/{fmt}')
            report.raise_for_status()
            (target / ('report.' + fmt)).write_bytes(report.content)
        (ROOT / 'work/end-to-end-ai.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        rendered = convert(target / 'report.docx', 'pdf:writer_pdf_Export', target / 'docx-render')
        import pypdfium2 as pdfium
        for source, label in ((target / 'report.pdf', 'pdf'), (rendered, 'docx')):
            pdf = pdfium.PdfDocument(source)
            for i, page in enumerate(pdf):
                page.render(scale=1.2).to_pil().save(target / f'{label}-{i+1}.png')
        print('PASS: 5 изменений, ИИ использован, 3 отчёта получены и отрисованы.', flush=True)
        print('http://localhost:8080/#task=' + jid, flush=True)


if __name__ == '__main__':
    main()
