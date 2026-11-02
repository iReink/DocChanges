"""One private, prewarmed LibreOffice instance owned by the comparison server."""
import os
import subprocess
import uuid
import threading
from pathlib import Path
from shared.settings import ROOT


class Converter:
    def __init__(self):self.process=None;self.pipe=None;self.python=None;self.ready=False;self.probe=None;self.closed=False;self.error=None

    def status(self):return {'enabled':bool(self.pipe),'ready':self.ready,'state':'ready' if self.ready else ('error' if self.error else 'warming' if self.pipe else 'disabled')}

    def start(self):
        self.closed=False;self.ready=False;self.error=None
        program=ROOT/'runtime/libreoffice/App/libreoffice/program'
        self.python=program/'python.exe';exe=program/'soffice.exe'
        if not exe.is_file() or not self.python.is_file():return
        self.pipe='atlas_'+uuid.uuid4().hex
        profile=ROOT/'temp/converter-sessions'/self.pipe;profile.mkdir(parents=True,exist_ok=True)
        args=[str(exe),'-env:UserInstallation='+profile.as_uri(),'--headless','--nologo','--nodefault','--norestore',
              '--accept=pipe,name='+self.pipe+';urp;StarOffice.ServiceManager']
        self.process=subprocess.Popen(args,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        os.environ['ATLAS_UNO_PIPE']=self.pipe
        print('Конвертер LibreOffice прогревается в фоне. Повторный запуск для каждого файла не требуется.',flush=True)
        threading.Thread(target=self._probe,daemon=True).start()

    def _probe(self):
        try:
            self.probe=subprocess.Popen([str(self.python),str(ROOT/'scripts/uno_convert.py'),'--pipe',self.pipe,'--keepalive'],
                cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            line=self.probe.stdout.readline()
            if not self.closed:
                self.ready=b'"ready": true' in line;self.error=None if self.ready else 'startup_failed'
                print('Конвертер LibreOffice готов.' if self.ready else 'Конвертер не завершил прогрев. Перезапустите сервер сравнения.',flush=True)
            self.probe.wait()
            if not self.closed:self.ready=False;self.error='converter_stopped'
        except Exception:self.error='startup_failed'

    def close(self):
        self.closed=True
        if not self.pipe:return
        try:
            subprocess.run([str(self.python),str(ROOT/'scripts/uno_convert.py'),'--pipe',self.pipe,'--shutdown','--wait','1'],
                cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except Exception:pass
        if self.process and self.process.poll() is None:
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(self.process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            else:self.process.terminate()
        if self.probe and self.probe.poll() is None:self.probe.terminate()
        os.environ.pop('ATLAS_UNO_PIPE',None)
        self.ready=False;self.pipe=None


converter=Converter()
