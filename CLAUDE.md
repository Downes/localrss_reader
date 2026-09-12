# LocalRSS Reader (/srv/apps/localrss_reader)

## Overview
Python/Flask RSS reader with SQLite backend.
GitHub: https://github.com/Downes/localrss_reader

## Container
- Name: localrss_reader-localrss-1  Port: 8787

## Database
- Directory: /srv/apps/localrss_reader/data/
- Supports multiple SQLite .db files; app scans for all *.db at startup.
- Current databases: rss.db, Podcasts.db
- Never delete or overwrite any .db file without permission.

## Database Sync
```bash
# Local to VPS
scp E:\localRSS\rss.db ubuntu@158.69.209.43:/srv/apps/localrss_reader/data/rss.db

# VPS to Local
scp ubuntu@158.69.209.43:/srv/apps/localrss_reader/data/rss.db E:\localRSS\rss.db
```

## Deployment
`app.py`, `feeds.opml`, and `static/` are all `COPY`'d into the image in the Dockerfile — none of them are bind-mounted. Editing any of these on disk has **no effect** on the running container until you rebuild and restart:
```bash
docker compose build localrss
docker compose up -d localrss
```
Only `./data` (the SQLite DBs) is bind-mounted and survives a rebuild untouched.
