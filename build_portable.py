"""Build a portable Windows folder using the installed CPython runtime and csc."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / 'outputs' / 'HogwartsLocal'
OUT.mkdir(parents=True, exist_ok=True)
runtime = OUT / 'runtime'
runtime.mkdir(exist_ok=True)
base = Path(sys.base_prefix)
for name in ('python.exe', 'pythonw.exe', 'python3.dll', f'python{sys.version_info.major}{sys.version_info.minor}.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt'):
    shutil.copy2(base / name, runtime / name)
dlls = runtime / 'DLLs'
dlls.mkdir(exist_ok=True)
for f in (base / 'DLLs').iterdir():
    if f.suffix in ('.dll', '.pyd') and not f.name.startswith(('_test', '_ctypes_test', '_tkinter', 'tk86', 'tcl86')):
        shutil.copy2(f, dlls / f.name)
version = f'python{sys.version_info.major}{sys.version_info.minor}'
with zipfile.ZipFile(runtime / (version + '.zip'), 'w', zipfile.ZIP_DEFLATED) as z:
    for f in (base / 'Lib').rglob('*'):
        rel = f.relative_to(base / 'Lib')
        if f.is_file() and not any(p in ('site-packages', '__pycache__', 'test', 'tests', 'idlelib', 'tkinter', 'ensurepip', 'turtledemo') for p in rel.parts):
            z.write(f, rel.as_posix())
(runtime / (version + '._pth')).write_text(version + '.zip\nDLLs\n.\n../app\n', encoding='utf-8')
app = OUT / 'app'
app.mkdir(exist_ok=True)
for name in ('server.py', 'launch.py', 'chatgpt_auth.py', 'context_pack.py'):
    shutil.copy2(ROOT / name, app / name)
for name in ('web', 'starter'):
    shutil.copytree(ROOT / name, app / name, dirs_exist_ok=True)
compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
subprocess.run([str(compiler), '/nologo', '/target:winexe', '/reference:System.Windows.Forms.dll', '/out:' + str(OUT / 'HogwartsLocal.exe'), str(ROOT / 'Launcher.cs')], check=True)
shutil.copy2(ROOT / 'README.md', OUT / 'README.md')
(OUT / 'Личное-прохождение.bat').write_text('@echo off\ncd /d "%~dp0"\nstart "" HogwartsLocal.exe --personal\n', encoding='utf-8')
subprocess.run([str(runtime / 'python.exe'), '-c', 'import server,ssl,sqlite3,ctypes; print("Portable runtime OK")'], check=True, env={**os.environ, 'RPG_DATA_DIR':str(ROOT.parent / 'work' / 'runtime-check')})
archive = ROOT.parent / 'outputs' / 'HogwartsLocal-Windows.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in OUT.rglob('*'):
        if f.is_file() and '__pycache__' not in f.parts:
            z.write(f, 'HogwartsLocal/' + f.relative_to(OUT).as_posix())
    for f in ROOT.rglob('*'):
        if f.is_file() and not any(p in ('.git', '.venv', 'data', '__pycache__', 'build', 'dist', 'outputs', 'runtime') for p in f.relative_to(ROOT).parts) and not f.name.startswith('.env') and f.suffix not in ('.dpapi', '.sqlite3', '.log') and '.sqlite3-' not in f.name:
            z.write(f, 'source/' + f.relative_to(ROOT).as_posix())
print(archive)
