import subprocess,sys,time,os
from comparison_server.jobs import Jobs

def test_expiration(tmp_path):
    manager=Jobs(tmp_path/'tasks');manager.start()
    try:
        folder=manager.root/'expired';folder.mkdir();(folder/'original').write_bytes(b'doc')
        with manager.lock:manager.items['expired']={'id':'expired','state':'completed','touched':0,'process':None}
        for _ in range(20):
            if not folder.exists():break
            time.sleep(.1)
        assert manager.get('expired') is None and not folder.exists()
    finally:manager.close()

def test_cancel_running_process(tmp_path):
    manager=Jobs(tmp_path/'tasks');folder=manager.root/'active';folder.mkdir()
    process=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        manager.items['active']={'id':'active','state':'running','process':process,'touched':time.time()}
        manager.delete('active');process.wait(timeout=5)
        assert not folder.exists() and manager.get('active') is None
    finally:
        if process.poll() is None:process.kill()

def test_stage_update_with_open_reader(tmp_path):
    from comparison_server.runner import write_stage
    write_stage(tmp_path,'Подготовка')
    with (tmp_path/'stage.txt').open('r',encoding='utf-8'):
        write_stage(tmp_path,'Сопоставление структуры')
    assert (tmp_path/'stage.txt').read_text(encoding='utf-8')=='Сопоставление структуры'
