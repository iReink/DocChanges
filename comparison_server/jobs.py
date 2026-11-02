import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from shared.settings import ROOT,settings

class Jobs:
    def __init__(self,root=None):
        self.root=root or ROOT/'temp/tasks';self.root.mkdir(parents=True,exist_ok=True)
        self.items={};self.garbage=set();self.lock=threading.RLock();self.stop=threading.Event();self.thread=None

    def start(self):
        self.stop.clear()
        self.items.clear()
        for folder in self.root.iterdir():
            if folder.is_dir():self.remove_folder(folder)
        self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()

    def close(self):
        self.stop.set()
        with self.lock:
            for job in self.items.values():
                if job.get('process'):self.kill(job['process'])
        if self.thread:self.thread.join(timeout=5)

    def kill(self,process):
        if process.poll() is not None:return
        if os.name=='nt':
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        else:process.terminate()

    def add(self,meta):
        with self.lock:
            if sum(v['state']=='queued' for v in self.items.values())>=settings()['queue_size']:
                raise ValueError('Очередь заполнена. Повторите позже.')
            self.items[meta['id']]={'id':meta['id'],'state':'queued','stage':'В очереди','created':time.time(),
                                    'touched':time.time(),'process':None,'error':None}

    def get(self,jid,touch=False):
        with self.lock:
            job=self.items.get(jid)
            if job and touch:job['touched']=time.time()
            if not job:return None
            return {k:v for k,v in job.items() if k!='process'}

    def delete(self,jid):
        with self.lock:
            job=self.items.pop(jid,None)
            if job and job.get('process'):self.kill(job['process'])
            self.remove_folder(self.root/jid)
            if (self.root/jid).exists():self.garbage.add(jid)

    def remove_folder(self,path):
        path.resolve().relative_to(self.root.resolve())
        if path.resolve()==self.root.resolve():raise ValueError('Нельзя удалить корневую папку задач.')
        shutil.rmtree(path,ignore_errors=True)

    def loop(self):
        while not self.stop.wait(.25):
            with self.lock:
                for orphan in list(self.garbage):
                    self.remove_folder(self.root/orphan)
                    if not (self.root/orphan).exists():self.garbage.discard(orphan)
                now=time.time();active=False
                for jid,job in list(self.items.items()):
                    folder=self.root/jid
                    if job['state']=='running':
                        process=job['process'];code=process.poll()
                        if now-job['started']>settings()['task_timeout_seconds']:
                            self.kill(process);job.update(state='failed',error='Превышено время обработки задачи.',touched=now)
                        elif code is not None:
                            success=code==0 and (folder/'result.json').exists()
                            err=(folder/'error.txt').read_text(encoding='utf-8') if (folder/'error.txt').exists() else 'Обработка прервана.'
                            job.update(state='completed' if success else 'failed',stage='Готово' if success else 'Ошибка',
                                       error=None if success else err,touched=now,process=None)
                        else:
                            active=True
                            try:
                                stage=(folder/'stage.txt').read_text(encoding='utf-8')
                                if stage.strip():job['stage']=stage
                            except (OSError,UnicodeError):pass
                    elif job['state'] not in ('queued','running') and now-job['touched']>settings()['idle_seconds']:
                        self.delete(jid)
                if not active:
                    job=next((j for j in self.items.values() if j['state']=='queued'),None)
                    if job:
                        creation=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
                        p=subprocess.Popen([sys.executable,'-m','comparison_server.runner',str(self.root/job['id'])],
                                           cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=creation)
                        job.update(state='running',started=now,stage='Подготовка',process=p)
