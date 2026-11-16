"""Build the local-only executable on the current operating system."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def main():
    separator = ';' if os.name == 'nt' else ':'
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
        '--console', '--hidden-import', 'app', '--name', 'LocalRSS', '--distpath', str(ROOT / 'dist'),
        '--workpath', str(ROOT / 'build' / 'desktop'), '--specpath', str(ROOT / 'build'),
        '--add-data', str(ROOT / 'static') + separator + 'static']
    for package in ('flask', 'aiohttp', 'feedparser', 'clist_server_admin', 'clist_kvstore_auth'):
        command.extend(['--collect-all', package])
    command.append(str(ROOT / 'desktop_launcher.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    executable = ROOT / 'dist' / ('LocalRSS.exe' if os.name == 'nt' else 'LocalRSS')
    subprocess.run([str(executable), '--self-test'], cwd=ROOT, check=True, timeout=60)

if __name__ == '__main__':
    main()
