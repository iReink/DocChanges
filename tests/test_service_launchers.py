import subprocess
from pathlib import Path


def test_windows_service_lifecycle(tmp_path):
    script=Path(__file__).with_name('service_lifecycle.ps1')
    result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),
                           '-CaseRoot',str(tmp_path/'Atlas test')],capture_output=True,timeout=30)
    assert result.returncode==0,(result.stdout+result.stderr).decode('utf8',errors='replace')
    assert b'PASS:' in result.stdout
