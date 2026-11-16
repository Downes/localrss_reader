"""Create a download with platform instructions, preserving Unix executable bits."""
from pathlib import Path
import shutil
import sys
import tarfile
import zipfile

PLATFORMS = ('windows-x64', 'linux-x64', 'macos-x64', 'macos-arm64')
ROOT = Path(__file__).resolve().parent


def package(platform):
    if platform not in PLATFORMS:
        raise ValueError('Unknown platform: ' + platform)
    executable = ROOT / 'dist' / ('LocalRSS.exe' if platform.startswith('windows') else 'LocalRSS')
    if not executable.is_file():
        raise FileNotFoundError(executable)
    # Separate staging per architecture; no source or database files are copied.
    staging = ROOT / 'build' / ('download-' + platform)
    staging.mkdir(parents=True, exist_ok=True)
    shutil.copy2(executable, staging / executable.name)
    text = ('LocalRSS standalone desktop\n\nRun ' + executable.name + ' to open LocalRSS in your browser.\n'
        'Keep the launcher window open; Ctrl+C stops the local service.\n'
        'Sign in using the existing kvstore login, then create/select a feed database.\n'
        'No Python, SSH, VPS or database synchronization is required.\n'
        'Updates do not replace your data stored in your user profile.\n'
        'macOS downloads are architecture-specific and not signed/notarized.\n'
        'Linux: launch ./LocalRSS from a terminal (requires a desktop browser).\n'
        'Documentation: https://github.com/Downes/localrss_reader/blob/main/README_DESKTOP.md\n')
    (staging / 'START_HERE.txt').write_text(text, encoding='utf-8')
    output = ROOT / 'release'
    output.mkdir(exist_ok=True)
    if platform.startswith('windows'):
        path = output / ('LocalRSS-' + platform + '.zip')
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in (executable.name, 'START_HERE.txt'):
                archive.write(staging / name, name)
    else:
        path = output / ('LocalRSS-' + platform + '.tar.gz')
        with tarfile.open(path, 'w:gz') as archive:
            for name in (executable.name, 'START_HERE.txt'):
                archive.add(staging / name, arcname=name)
    return path


if __name__ == '__main__':
    print(package(sys.argv[1]))
