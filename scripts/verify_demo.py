"""Integration verification of all nine directed format pairs and exports."""
import json,os,shutil,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shared.settings import ROOT
from comparison_server.extract import convert
from comparison_server.pipeline import run
from comparison_server.reports import make_report

def main():
    os.environ['ATLAS_MODELS_URL']='http://127.0.0.1:9'
    folder=ROOT/'work/verification';folder.mkdir(parents=True,exist_ok=True)
    files={}
    for side in ('old','new'):
        source=ROOT/'tests/fixtures'/(side+'.docx')
        files[side,'docx']=source
        for fmt,filter_name in [('doc','doc:MS Word 97'),('pdf','pdf:writer_pdf_Export')]:
            cached=folder/(side+'-'+fmt)/(side+'.'+fmt)
            files[side,fmt]=cached if cached.exists() else convert(source,filter_name,folder/(side+'-'+fmt))
    records=[]
    for oldfmt in ('docx','doc','pdf'):
        for newfmt in ('docx','doc','pdf'):
            case=oldfmt+'-'+newfmt;job=folder/case;job.mkdir(exist_ok=True)
            for side,fmt in [('old',oldfmt),('new',newfmt)]:
                (job/side).mkdir(exist_ok=True);shutil.copyfile(files[side,fmt],job/side/'original')
            meta={'id':case,'employee':'Тестовый сотрудник','old':{'name':'old.'+oldfmt},'new':{'name':'new.'+newfmt}}
            t=time.perf_counter();result=run(job,meta,lambda stage:None)
            types={cat for c in result['changes'] for cat in c['categories']}
            rowinsertions=sum(c['operation']=='row_insert' for c in result['changes'])
            record={'pair':case,'changes':result['count'],'categories':sorted(types),'row_insertions':rowinsertions,'seconds':round(time.perf_counter()-t,2),'warnings':result['warnings']}
            records.append(record);print(json.dumps(record,ensure_ascii=False),flush=True)
            assert {'money','dates','requisites','table'}<=types,(case,types)
            assert rowinsertions==1,(case,rowinsertions)
            if case=='docx-docx':
                assert result['count']==5,result['changes']
                for fmt in ('pdf','docx','json'):
                    (job/('report.'+fmt)).unlink(missing_ok=True)
                    make_report(result,job,fmt)
                converted=convert(job/'report.docx','pdf:writer_pdf_Export',job/'report-render')
                import pypdfium2 as pdfium
                for source,label in [(job/'report.pdf','pdf-report'),(converted,'docx-report')]:
                    pdf=pdfium.PdfDocument(source)
                    for i,page in enumerate(pdf):page.render(scale=1.3).to_pil().save(job/f'{label}-{i+1}.png')
    # Exact unchanged Word and PDF fixtures must not produce content changes.
    for fmt in ('docx','doc','pdf'):
        job=folder/('same-'+fmt);job.mkdir(exist_ok=True)
        for side in ('old','new'):
            (job/side).mkdir(exist_ok=True);shutil.copyfile(files['old',fmt],job/side/'original')
        meta={'id':'same-'+fmt,'employee':'Тест','old':{'name':'old.'+fmt},'new':{'name':'old.'+fmt}}
        result=run(job,meta,lambda stage:None);assert result['count']==0,(fmt,result['changes'])
    (folder/'matrix.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Проверены 9 пар форматов, 3 неизменённых пары, отчёты PDF/DOCX/JSON.',flush=True)

if __name__=='__main__':main()
