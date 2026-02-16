# LocalRSSReader v0.4.9

Fix:
- Resolves "mktime argument out of range" by using safe date conversion for feedparser struct_time values.
  - Some feeds emit invalid years (e.g. 0001 or 9999), which can crash time.mktime() on Windows.
  - We clamp absurd years and fall back to "now" rather than crashing the whole update job.
- Per-entry and per-feed parsing errors are counted as errors and the update continues.

Everything else:
- Progress + Cancel for Update now
- Background updating toggle
- DB write serialization to avoid "database is locked"

If you want to identify which feed caused the bad date, we can add a small log file later.


v0.4.8 UI tweaks:
- Expand is instant (mark-read happens in background)
- Relative/same-origin links inside entry content open in a new tab


v0.4.8:
- All links in feed content (internal and external) open in a new tab


v0.4.8 performance:
- Stops re-rendering the entire list on every click/keypress
- Injects entry HTML only when you expand that entry (huge speed-up for big feeds)


v0.4.8 keyboard:
- J/K now move selection AND expand the newly selected entry (collapsing the previous one)


v0.4.8 UI/keyboard:
- Adds a Collapse button on expanded entries
- J/K now expand and scroll the selected entry so its headline is at the top of the viewport


v0.4.8 display:
- Images inside entries are constrained to a maximum width of 500px


v0.4.8 images:
- Images are responsive (max-width: min(500px, 100%))
- Click-to-zoom: clicking an image in an expanded entry opens the image in a new tab


v0.4.8 layout:
- Adds collapsible left sidebar (hamburger)
- Mobile sidebar overlays at 100% width; desktop sidebar max 400px
- Sidebar + main never exceed 100% width (flex layout / overlay)


v0.4.8 startup:
- Prevents double-launch (single-instance lock + port check)
- Only the batch file opens the browser (no second window from app.py)


v0.4.8 startup:
- run_localrss.bat no longer spawns a second terminal window
- uses venv\Scripts\python.exe explicitly (no activate), so it can't accidentally use an old venv
- only one long-running python.exe remains (the server)


v0.4.8 layout:
- Sidebar overlay starts hidden; hamburger toggles open/closed
- CSS cleaned to remove conflicting prior sidebar rules
- Zip root folder name matches release version


v0.4.8 DB visibility:
- run_localrss.bat sets RSS_DB=E:\localRSS\rss.db by default
- UI shows DB path at top (and marks it missing if not found)


v0.4.8 diagnostics:
- run_localrss.bat logs to localrss_run.log and pauses on errors so crashes are visible


v0.4.8 robustness:
- Creates missing DB directory for RSS_DB paths.
- If configured DB can't be opened, falls back to local rss.db instead of crashing.
- UI shows Active vs Configured DB path.
