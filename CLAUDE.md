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

## Auth
All endpoints require a kvstore login **except** `/`, `/static/*`, and `/api/collections*` (public, see below).
- Client sends `Authorization: Bearer <token>`, plus `X-Kvstore-Url: <issuing kvstore instance>` (still sent by CList's `rss.js` on every request, but now only consulted for the legacy case below).
- Token verification is local JWT/JWKS ("Pattern B") via the shared
  `clist-kvstore-auth` package (`clist_kvstore_auth.sync`), pinned by commit
  SHA in `requirements.txt` (github.com/Downes/clist-kvstore-auth),
  `verify_identity()` in `app.py`. A JWT's own `iss` claim names the
  instance that signed it; we fetch *that* instance's `/.well-known/jwks.json`
  and verify the signature — open to any issuer, no allowlist (anyone can run
  their own kvstore and interoperate). The `X-Kvstore-Url` header is no
  longer consulted for a real JWT.
- Opaque (pre-migration) tokens carry no `iss` and can't be verified
  locally, so they still fall back to `GET {X-Kvstore-Url}/auth/verify` —
  but that header's value must be one of `_allowed_kvstore_urls()`
  (comma-separated; `RSS_ALLOWED_KVSTORE_URLS` env var is the fallback
  default `https://kvstore.mooc.ca,https://kvstore.downes.ca`, overridden by
  `app_settings.RSS_ALLOWED_KVSTORE_URLS` once an admin saves one — see
  Admin settings below), same allowlist now also used to decide which
  issuer(s) are trusted to vouch for an `ADMIN_USERNAMES` admin.
- No per-user ownership model exists in this app (no "my feeds are mine"
  column) — `g.identity`/`g.username` are set for display/admin-gating only,
  not compared against any stored owner.
- `/admin/settings` is additionally gated by `is_admin(identity)` in
  `app.py`, reimplemented locally rather than using
  `clist_kvstore_auth.sync.is_admin()` directly, because
  `RSS_ALLOWED_KVSTORE_URLS` is DB-overridable here (not just a static env
  var) — see Admin settings below.
- The admin UI (`static/index.html`) has its own kvstore login form (overlay shown when logged out) and a global `window.fetch` override that attaches the auth headers to any `/api/*` or `/fetch_feed` request and logs out on a 401.
- Caddy CORS: `localrss.downes.ca`'s own block scopes non-collections routes to origin `https://clist.mooc.ca`; `kvstore.mooc.ca` and `kvstore.downes.ca` both allow origin `https://localrss.downes.ca` (needed for the admin UI's login calls).

## Admin settings
Generic admin-editable runtime settings — imported from the shared
`clist-server-admin` package (`clist_server_admin.sqlite`), pinned by commit
SHA in `requirements.txt` (github.com/Downes/clist-server-admin). No local
`admin_settings.py` copy anymore. `ADMIN_USERNAMES` (`docker-compose.yml`
environment block, comma-separated — this app has no `.env` file, env vars
are set directly in compose) gates `/admin/settings` (Bearer token +
username in that set, else 403). Two fields: `ENABLED` (boolean, default
`true`) — kill switch, see below — and `RSS_ALLOWED_KVSTORE_URLS`
(non-sensitive, comma-separated).

Three things differ from the pastebin/survey pilots because of this app's own
architecture:
- `verify_identity(req)` here takes the Flask request explicitly (unlike
  pastebin/survey's no-arg version), and the app already has a global
  `@app.before_request` auth gate (`_require_auth`) that runs it for every
  non-public path, `/admin/settings` included, stashing the result on
  `g.identity`. The callable passed to `register_admin_settings_routes()`
  is `_admin_verify_token()`, which reuses `g.identity` (no second
  round-trip to kvstore) but additionally gates on this app's own
  issuer-aware `is_admin(identity)` before returning a username — otherwise
  `clist_server_admin.sqlite`'s own bare `is_admin(username)` (env
  `ADMIN_USERNAMES` membership only, no issuer check) would let any
  issuer's JWT naming `sub=<admin username>` through, which would defeat
  the point of ordinary verification being open to any issuer.
- A separate `@app.before_request` hook, `_enabled_gate()`, is registered
  **above** `_require_auth()` in `app.py` (Flask runs before_request hooks
  in registration order), so when `ENABLED` is `false` the app answers
  `503 {"error": "Service temporarily disabled by administrator"}` for
  every route except `/admin/settings` without first paying for a
  token-verify round trip to kvstore. This includes the normally-public
  `/`, `/static/*`, and `/api/collections*` paths — the kill switch is
  app-wide.
- This app supports multiple switchable personal SQLite DB files
  (`rss.db`, `Podcasts.db`, ...). Admin settings must not appear to reset
  when the active DB is switched, so they live in their own dedicated file,
  `data/admin_settings.db`, opened via `get_admin_settings_db()` — completely
  independent of `connect_db()`/`get_db()` (the switchable personal DB) and
  of the per-collection DBs.

`SETTINGS_DEFAULTS` (in `app.py`) holds the same env-sourced fallback
`_allowed_kvstore_urls()` uses at its point of use, so `GET /admin/settings`
shows the actual effective value instead of a blank field when no override
has been saved yet. The `SettingField` also carries a `help` string,
surfaced by CList's "Help" button/modal in the App Settings panel.

## Collections
Predefined, file-based RSS collections, independent of any personal `.db`, harvested by their own scheduler loop and exposed publicly (no auth) for any CList instance to consume.
- Manifests: bind-mounted JSON files under `./data/collections/manifests/*.json`, each `{"slug": "...", "title": "...", "feeds": [...]}`. Slug must match `^[A-Za-z0-9_-]+$`.
- Each manifest gets its own SQLite DB at `./data/collections/<slug>.db`, schema-identical to the personal DBs, created/synced by `ensure_collections()` at startup and on each scheduler tick.
- Feed sync is **add-only** (`ensure_feed` / `INSERT OR IGNORE`) — editing a manifest never deletes feeds from the collection DB.
- Public endpoints (CORS `Access-Control-Allow-Origin: *`, no credentials):
  - `GET /api/collections` — list of `{slug, title, feed_count}`
  - `GET /api/collections/<slug>/items?limit=200` — ranked items from that collection
- To add a new collection: drop a manifest JSON file into `./data/collections/manifests/` — no restart required, it's picked up by `ensure_collections()` on the next scheduler tick (or restart the container to pick it up immediately).

## Environment variables (set in `docker-compose.yml`, no `.env` file)
- `RSS_DB`                   — Path to the default/startup SQLite DB file (default: /data/rss.db)
- `RSS_PORT`                 — Internal port (default: 8787)
- `RSS_ALLOWED_KVSTORE_URLS` — Comma-separated kvstore instances trusted to vouch for an
  `ADMIN_USERNAMES` admin, and valid opaque/legacy-token fallback targets (named by a
  client's `X-Kvstore-Url` header) (default: https://kvstore.mooc.ca,https://kvstore.downes.ca)
  — fallback; overridden by `app_settings.RSS_ALLOWED_KVSTORE_URLS` once an admin saves one.
  Does NOT gate ordinary token verification, which is open to any issuer.
- `ADMIN_USERNAMES`          — Comma-separated kvstore usernames allowed to use `/admin/settings`

## Background Scheduler
`start_background_scheduler()` runs at **module level** (not inside `if __name__ == "__main__":`), so it actually starts under gunicorn in production. It launches two asyncio loops in a daemon thread: `scheduler_loop()` (personal DBs) and `collections_scheduler_loop()` (collection DBs, serialized via `COLLECTIONS_WRITE_LOCK` so collection creation/sync and scheduled fetches never race).
