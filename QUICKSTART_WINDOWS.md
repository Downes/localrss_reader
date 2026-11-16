# LocalRSS for Windows

1. Download **LocalRSS-windows-x64.zip** from the
   [latest desktop release](https://github.com/Downes/localrss_reader/releases/latest).
2. Extract the ZIP and double-click **LocalRSS.exe**.
3. LocalRSS opens in your browser. Sign in with your kvstore account, then
   create/select a database and add feeds or import OPML.

Keep the launcher window open while reading. Ctrl+C stops LocalRSS.
No Python installation, build step, SSH key or VPS setup is required.
Your data is stored in `%LOCALAPPDATA%\LocalRSS` by default; updating the
executable does not replace it.

If port 8787 is occupied (for example by CList + LocalRSS), stop the other instance
or run `LocalRSS.exe --port 8788`. Downloads are not code-signed: follow your
normal software approval process if Windows shows a publisher/security prompt.

See the [desktop guide](README_DESKTOP.md) for other platforms and source builds.
The old SSH-based tray utility is documented in [Legacy VPS sync](LEGACY_DESKTOP_SYNC.md).
