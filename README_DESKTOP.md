# LocalRSS standalone downloads

Download from [Releases](https://github.com/Downes/localrss_reader/releases/latest):

| Platform | Archive | Start |
|---|---|---|
| Windows x64 | LocalRSS-windows-x64.zip | Extract; double-click LocalRSS.exe |
| Linux x64 | LocalRSS-linux-x64.tar.gz | Extract; run ./LocalRSS in a terminal |
| Intel Mac | LocalRSS-macos-x64.tar.gz | Extract; run ./LocalRSS in Terminal |
| Apple Silicon Mac | LocalRSS-macos-arm64.tar.gz | Extract; run ./LocalRSS in Terminal |

The launcher starts a local service at http://127.0.0.1:8787 and opens your browser.
Keep its window open; Ctrl+C stops the service. Python, SSH and a VPS are not
required. Use the existing kvstore login, create/select a database, and add feeds
or import OPML. Authentication and ownership rules remain unchanged.

Builds are not publisher-signed or Apple-notarized; follow your operating system's normal approval
process. Choose the Mac archive matching your CPU. Linux builds target Ubuntu
22.04 or later compatible x64 systems with a browser. Archives preserve executable
permissions. If port 8787 is in use, stop the other LocalRSS instance or use
`--port 8788`. `--no-browser` suppresses opening the browser. The service binds
only to loopback.

## Your data

| Platform | Default folder |
|---|---|
| Windows | %LOCALAPPDATA%\LocalRSS |
| macOS | ~/Library/Application Support/LocalRSS |
| Linux | $XDG_DATA_HOME/localrss, or ~/.local/share/localrss |

The database is `global.db` in that folder. Updating the executable preserves it.
`RSS_DESKTOP_DATA_DIR` chooses another folder; `RSS_DB` explicitly selects an
existing compatible database. No automatic database copying, VPS synchronization
or bundled subscription import is performed.

## Build from source (developers)

Use Python 3.12, from the repository root:

```text
python -m pip install -r requirements-standalone.txt
python -m unittest discover -s tests -p 'test_*.py' -v
python desktop_launcher.py --self-test
python build_standalone.py
```

Build on each target OS/architecture. The builder checks the finished executable
with `--self-test`: temporary SQLite, local HTTP pages/assets, harvester locking
and the authentication gate, without starting harvesting or opening a browser.
`python package_standalone.py windows-x64` creates the Windows archive; use
linux-x64, macos-x64 or macos-arm64 for the other variants.

## Automated releases

`.github/workflows/desktop.yml` builds all four variants on push to main or manual
dispatch. Pull requests are validated without publishing. All platforms must pass
tests and the packaged smoke check before publishing a release. Release tags
include the source commit; no developer credentials are embedded.

The older tray/SSH tool remains available separately; see
[Legacy VPS sync](LEGACY_DESKTOP_SYNC.md). New downloads never run it.

Local verification (2026-11-15): seven Python tests passed, and a Windows one-file
executable passed the real temporary-DB/HTTP/authentication/locking smoke check.
Workflow YAML parsed with all four variants. macOS/Linux builds and release
publication await execution in GitHub Actions; no live-account writes were tested.
