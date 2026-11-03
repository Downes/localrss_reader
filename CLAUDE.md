# LocalRSS Reader (/srv/apps/localrss_reader)

## Overview
Python/Flask RSS reader with SQLite backend.
GitHub: https://github.com/Downes/localrss_reader

## Role in CList's Deployment Configurations

The name is the intent: this app was designed to run **locally**, not as a centrally-hosted
service — the hosted container at `localrss.downes.ca` is a convenience, not the point. Deployed
separately from the [CList](https://github.com/Downes/CList) codebase on purpose, to keep CList's
own repo from growing a full RSS-reader-with-storage inside it.

CList can be served three ways (hosted web, local desktop launcher, or raw `file://`), and its
data can live in two places (browser IndexedDB, or a remote/local service) — six configurations
in total. See CList's own `docs/deployment-configurations.md` for the full matrix. Today, this app
only participates in **one** of CList's features across all six: the public, anonymous
**Collections** API (`/api/collections*`, open CORS) backing `js/public-feeds.js`. CList's
*personal* feed reading (a logged-in user's own subscriptions, read state, bookmarks) never talks
to this app at all — it always goes through opml2json (stateless fetch) + browser IndexedDB
(storage), the same way in all six configurations.

**Vendored copy for desktop executables.** Separately from the integration work below, CList's
"CList + LocalRSS" desktop builds bundle a vendored snapshot of `app.py` + `feeds.opml` at
`/srv/www/clist.mooc.ca/localrss_bundled/`, pinned to a commit SHA (see the header comment there)
the same way `kvstore` pins `clist-server-admin`/`clist-kvstore-auth` — bump it when resyncing, so
the executable gives a non-technical user a working local LocalRSS instance with no separate
install. See
`/srv/www/clist.mooc.ca/CLAUDE.md`'s "Desktop Launcher" section for how it's spawned. The vendored
copy has one intentional deviation from this file (`fcntl` import moved/guarded for Windows
compatibility) — **do not** apply that change here; this app always runs on Linux under gunicorn.

**The goal:** make this app CList's personal-feed-harvesting backend too, local-first — run it on
your own machine (ideal) when you can, fall back to a remote instance (`localrss.mooc.ca` or
similar) when you can't. Not yet built. What's blocking it, in order:

1. **No CORS handling in `app.py` itself.** Every CORS header this app ever sends comes from the
   Caddy block in front of the *hosted* instance (`/srv/proxy/Caddyfile`'s `localrss.downes.ca`
   block). A bare local run — `run_localrss.sh`/`run_localrss.bat`, the Windows tray app, or a
   plain `docker compose up` with nothing in front of it — answers every request with **zero**
   `Access-Control-Allow-*` headers. That means no browser page — hosted CList, the desktop
   launcher, or `file://` — can currently `fetch()` a locally-run instance, in *any* of the six
   configurations. This is the first thing that needs fixing, e.g. an `after_request` hook that
   always allows CORS when bound to `127.0.0.1` (not internet-reachable, so no exposure from
   being permissive there).
2. **No integration path from CList's side.** `js/rss.js` has no concept of a LocalRSS instance —
   only `OPML2JSON` (fetch-only, no storage). The natural shape, matching the existing
   `OPML2JSON` schema pattern (`kvKey`/`instance`, a configurable Service URL with a built-in
   default): a new account type pointed at a LocalRSS instance URL, using this app's richer
   `/api/items`, `/api/mark_read`, `/api/toggle_bookmark` routes as the backing store instead of
   IndexedDB.
3. **No local-first/remote-fallback logic anywhere.** Probing for a local instance
   (`http://localhost:8787`), preferring it when reachable, and falling back to a configured
   remote URL or to IndexedDB otherwise, is new application logic in CList — doesn't exist today.
4. **Remote-instance CORS would need origin allow-listing for configs 3–6** (the desktop
   launcher's `127.0.0.1` origin, and `file://`'s `null` origin) the same way kvstore's Caddy
   config already does for *its* `127.0.0.1` case — see `/srv/proxy/Caddyfile`'s
   `@options_localhost`/`@cors_localhost` blocks on `kvstore.mooc.ca` as the pattern to copy. The
   current `localrss.downes.ca` Caddy block only allow-lists `https://clist.mooc.ca` for
   non-collections routes.

Running this app locally is already fully solved on every major platform — see
`README_DESKTOP.md` (Windows, system tray + SSH DB sync), `RUNNING_ON_MAC_LINUX.md` (pre-alpha
shell script), and the `Dockerfile`/`docker-compose.yml` (same image, run anywhere). The gap is
entirely on the *integration* side (items 1–4 above), not on "can this run locally."

## Container
- Name: localrss_reader-localrss-1  Port: 8787

## Database
**Verified against `app.py` 2026-11-02 — the old multi-file model below is gone, not "pending."**
There is no more `ACTIVE_DB_PATH`/startup `*.db` scan at all; that code has been removed. One
global SQLite file, path set by the `RSS_DB` env var (`docker-compose.yml`:
`RSS_DB=/data/global.db`), holds everything — see "Architecture: Global Harvest Store" below for
the schema. `migrate_to_global_schema.py` (in this app's directory) already ran: `data/global.db`
is live in production with 7 rows in `databases` — personal (owner=downes):
`rss`/`podcasts`/`Cogdog_Podcasts`/`OpenEd_Podcasts`; public/collections (owner=NULL):
`news`/`sessions`/`technology`. The pre-migration files (`data/rss.db`, `data/Podcasts.db`,
`data/news.db`, `data/sessions.db`, `data/technology.db`) are still present on disk, untouched per
the "never delete/overwrite without permission" rule, but are **not read by the running app** —
don't confuse them with the live data in `global.db`.
- Directory: /srv/apps/localrss_reader/data/
- Never delete or overwrite any .db file without permission.

## Database Sync
The live data is `data/global.db`, not `rss.db` — the commands below target the actual running
database (the old per-file `rss.db` commands this section used to show are stale and would
sync/restore the wrong file).
```bash
# Local to VPS
scp E:\localRSS\global.db ubuntu@158.69.209.43:/srv/apps/localrss_reader/data/global.db

# VPS to Local
scp ubuntu@158.69.209.43:/srv/apps/localrss_reader/data/global.db E:\localRSS\global.db
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
- This app supports multiple personal "databases" selectable via `?db=<slug>` or a per-identity
  preference (see "Architecture: Global Harvest Store" below — this predates and is now
  implemented by that global-schema `databases` table, not separate switchable `.db` files).
  Admin settings must not appear to reset when the selected database changes, so they live in
  their own dedicated file, `data/admin_settings.db`, opened via `get_admin_settings_db()` —
  completely independent of `GLOBAL_DB_PATH`/`connect_global()`.

`SETTINGS_DEFAULTS` (in `app.py`) holds the same env-sourced fallback
`_allowed_kvstore_urls()` uses at its point of use, so `GET /admin/settings`
shows the actual effective value instead of a blank field when no override
has been saved yet. The `SettingField` also carries a `help` string,
surfaced by CList's "Help" button/modal in the App Settings panel.

## Architecture: Global Harvest Store + Per-Database Views (core schema LIVE as of 2026-11-02)

**Status:** the global `feeds`/`entries`/`databases`/`database_feeds`/`entry_status` schema and
`resolve_database()` are confirmed implemented and in use in `app.py`. Build sequence tracked as
Phase 2a in `/srv/shared/clist-private/localrss-integration-plan.md`. **Full line-by-line
re-verification against `app.py` done 2026-11-02** — every sub-claim below (migration status,
ownership-model enforcement, feed-removal orphan-sweep semantics, retention, collections) has now
been checked against the live code; corrections from that pass are inlined below where they
differ from the original design notes. The "pending the rework" framing still on the Collections
subsection further down is itself now stale — see the correction there.

**Problem this replaces:** today, each personal DB file (`rss.db`, `Podcasts.db`) and each
collection DB (`data/collections/<slug>.db`, see below) independently harvests and stores its own
copy of every feed it lists — the same feed URL appearing in two DBs gets fetched and stored
twice. Worse, the single "active" personal DB is a global, server-process-wide pointer
(`ACTIVE_DB_PATH`, switched via `POST /api/db_select`), which only ever worked because exactly one
person used exactly one DB at a time — it can't support multiple CList accounts hitting one shared
LocalRSS instance against different databases concurrently without one request's DB switch racing
another's.

**New model — schema locked in 2026-10-31**, one global SQLite DB replacing the per-file model:

```sql
-- Global, deduplicated feed metadata — one row per URL across the whole instance.
CREATE TABLE feeds (
    id            INTEGER PRIMARY KEY,
    url           TEXT NOT NULL UNIQUE,
    title         TEXT,
    etag          TEXT,
    last_modified TEXT,
    last_fetch    INTEGER,
    fail_count    INTEGER DEFAULT 0,
    next_fetch    INTEGER DEFAULT 0,
    month_count   INTEGER DEFAULT 0,
    last_ok       INTEGER DEFAULT 0,
    error_msg     TEXT,
    feed_author   TEXT,
    feed_image    TEXT,
    feed_author_did TEXT   -- added later via _ensure_column(), not in the original CREATE TABLE
);

-- Global, deduplicated entries. No read_at/bookmarked here — see entry_status.
CREATE TABLE entries (
    id           INTEGER PRIMARY KEY,
    feed_id      INTEGER NOT NULL REFERENCES feeds(id),
    guid         TEXT NOT NULL,
    title        TEXT,
    link         TEXT,
    author       TEXT,
    published    INTEGER,
    content_html TEXT,
    thumbnail    TEXT,
    created_at   INTEGER NOT NULL,   -- when *this instance* first harvested it
    audio_url    TEXT,   -- added later via _ensure_column(), not in the original CREATE TABLE
    UNIQUE(feed_id, guid)
);
CREATE INDEX idx_entries_feed_pub ON entries(feed_id, published);

-- A named feed list. owner NULL = public/collection-style (world-readable, no status).
-- slug is NOT globally unique -- two different owners may each name a database
-- "rss" without colliding. Uniqueness is scoped to the full owner identity
-- (kvstore_url, kvkey) for owned databases, and to one shared public namespace
-- for owner-less (collection) ones.
CREATE TABLE databases (
    id                INTEGER PRIMARY KEY,
    slug              TEXT NOT NULL,
    title             TEXT,
    owner_kvstore_url TEXT,
    owner_kvkey       TEXT,
    created_at        INTEGER NOT NULL,
    CHECK ((owner_kvstore_url IS NULL) = (owner_kvkey IS NULL))
);
CREATE UNIQUE INDEX idx_databases_public_slug
    ON databases(slug) WHERE owner_kvkey IS NULL;
CREATE UNIQUE INDEX idx_databases_owner_slug
    ON databases(owner_kvstore_url, owner_kvkey, slug) WHERE owner_kvkey IS NOT NULL;

-- Membership: which feeds are in which database.
CREATE TABLE database_feeds (
    database_id INTEGER NOT NULL REFERENCES databases(id),
    feed_id     INTEGER NOT NULL REFERENCES feeds(id),
    added_at    INTEGER NOT NULL,
    PRIMARY KEY (database_id, feed_id)
);

-- Per-database status overlay. Only table mark-read/bookmark ever writes to.
CREATE TABLE entry_status (
    database_id INTEGER NOT NULL REFERENCES databases(id),
    entry_id    INTEGER NOT NULL REFERENCES entries(id),
    read_at     INTEGER,
    bookmarked  INTEGER DEFAULT 0,
    PRIMARY KEY (database_id, entry_id)
);
CREATE INDEX idx_entry_status_db_read ON entry_status(database_id, read_at);
CREATE INDEX idx_entry_status_db_bookmarked ON entry_status(database_id, bookmarked);

-- Per-identity "current database" preference, backing POST/GET /api/db_select.
-- Not shown in earlier drafts of this doc -- confirmed live 2026-11-02.
CREATE TABLE user_prefs (
    owner_kvstore_url TEXT NOT NULL,
    owner_kvkey       TEXT NOT NULL,
    database_id       INTEGER NOT NULL REFERENCES databases(id),
    PRIMARY KEY (owner_kvstore_url, owner_kvkey)
);
```

**Compile step, concretely** (`GET /api/items?db=<slug>`):
0. Resolve `slug` to a `database_id`: for an owned database, the lookup must include the
   requester's own identity (`WHERE owner_kvstore_url=? AND owner_kvkey=? AND slug=?`) — never
   `slug` alone, since different owners can legitimately share a slug. For a public database,
   `WHERE owner_kvkey IS NULL AND slug=?`.
1. `feed_ids = SELECT feed_id FROM database_feeds WHERE database_id = ?`
2. `candidates = SELECT * FROM entries WHERE feed_id IN (feed_ids) ORDER BY published ...` — uses
   `idx_entries_feed_pub`, same index shape as today.
3. `statuses = SELECT entry_id, read_at, bookmarked FROM entry_status WHERE database_id = ? AND
   entry_id IN (candidate ids)` — single index lookup.
4. Merge 2+3 in application code (dict keyed by `entry_id`), then apply the existing
   filter/scoring logic unchanged.

No step above is a multi-column SQL `JOIN` — each is "rows for this key" — so it maps directly
onto IndexedDB's `getAll()`/index-cursor model if a client-side twin is ever needed: object stores
`feeds`, `entries`, `database_feeds`, `entry_status` with matching indexes, three sequential
`getAll()` calls instead of one SQL query.

**Migration data-shape note (confirmed empirically 2026-10-31 via the live DBs):**
`Podcasts.db`'s `feeds`/`entries` tables predate several columns present in `rss.db` and the
collection DBs (`error_msg`, `feed_author`, `feed_image` on `feeds`; `author`, `thumbnail` on
`entries`) — the migration script must default those to `NULL` for rows sourced from
`Podcasts.db`.

**Ownership & permissions — resolved 2026-10-31, status code corrected 2026-11-02:** this is the
app's first ownership model — today `g.identity` is display/admin-only (see Auth section above:
"no per-user ownership model exists... no 'my feeds are mine' column"). Only a database's owner
may edit its feed list or write `entry_status` rows for it; `resolve_database(..., for_write=True)`
rejects a non-owner write with 403 "read-only" (`app.py:1140`). **Reads of a personal (owned)
database are also owner-restricted, but the mismatch surfaces as a 404, not a 403** — verified
against `get_database_by_slug()`/`resolve_database()` (`app.py:1124-1176`): a slug lookup scoped to
the *caller's own* identity simply finds no row for another owner's private database, falls
through to the public-database check, finds nothing there either, and returns 404 "Unknown
database: `<slug>`". There's no separate "exists but you can't see it" branch producing a 403 —
which is arguably the better behavior (doesn't confirm a private slug's existence to a non-owner),
but don't rely on 403 specifically if you're writing code or tests against this. Collections
(`owner = NULL`) stay world-readable, no auth, same as today.

**Feed-removal semantics — resolved 2026-10-31:** removing a feed from a personal database (`POST
/api/feed_delete`) deletes only that database's `database_feeds` membership row — it never deletes
the global `feeds`/`entries` rows directly, since another database (a different personal database,
a collection, or in the future another user's database) may reference the same feed URL. The
global `feeds` row (and its `entries`) is only actually removed once an orphan sweep finds zero
remaining `database_feeds` rows referencing it anywhere. This is a behavior change from today,
where `/api/feed_delete` hard-deletes the feed and its entries outright — today that's safe only
because every DB file is independent; once feeds are shared globally, a hard delete would have a
cross-database blast radius (deleting a feed from `rss.db` could silently wipe it out from under
`podcasts` or a collection, if they happened to share the URL).

**"Current database" selection — resolved 2026-10-31:** `POST /api/db_select` keeps its existing
request/response shape, but what it sets changes from a process-global `ACTIVE_DB_PATH` to a
**per-identity** "current database" preference (one row per owner identity, in the `databases`
machinery — not a column on `entries`/`feeds`). Every route that used to read the global falls
back to that caller's stored preference when no `?db=<slug>` query param is given, so
`static/index.html`'s existing JS (which never sends `?db=`) keeps working essentially unchanged
once a default exists. A future CList client (Phase 2) can instead pass `?db=<slug>` explicitly on
every call and never touch the preference at all. This is what actually fixes the original race —
the state is still mutable, but it's scoped per-caller instead of shared across every worker and
every user.

**Compiling a database view (request time, no stored join needed):** `GET /api/items?db=<slug>`
becomes: (1) look up the database's feed list, (2) fetch candidate entries for those feed IDs,
(3) overlay that database's `entry_status` rows by `(database_id, entry_id)`, (4) apply the
existing filter/ranking logic unchanged. Each step is a single-key-indexed lookup, not a
multi-table SQL-only join — deliberately, so this compile logic isn't foreclosed from ever being
mirrored against CList's IndexedDB-backed `RSS` reader (`js/rss.js`), which has no join support at
all; a design that only worked as one big SQL `JOIN` would need a from-scratch redesign to ever
run client-side.

**Harvesting & retention:** one scheduler loop over the union of every feed URL referenced by any
database (replacing the two separate loops described under Background Scheduler below), and one
retention policy over the global `entries` table (replacing today's per-DB-file trimming). A feed
enters the harvest set the moment any database first references its URL, and is never
re-harvested per-database afterward. Confirmed in `update_feeds_async()` (`app.py:790-801`): after
each harvest batch, `entries` rows past `cutoff_ts()` (`RSS_RETENTION_DAYS` env, default 30 days)
are purged — **except** any entry bookmarked in *any* database's `entry_status`
(`WHERE entry_id NOT IN (SELECT entry_id FROM entry_status WHERE bookmarked = 1)`), with the
corresponding `entry_status` rows cascade-deleted first. This bookmark exemption wasn't in the
original design note above — it's a real, live behavior.

**Admin visibility:** a new "Harvester" panel in the admin dashboard (alongside the existing
`/admin/settings` infra from `clist_server_admin.sqlite`, see Admin settings above) — per-feed
last-fetched/next-fetch time, error count/last error, total feed/entry counts, manual re-fetch
trigger. Not yet designed in detail.

**Migration — DONE, confirmed live 2026-11-02 (was framed as a future step in earlier drafts of
this doc):** `migrate_to_global_schema.py` (in this app's directory) has already been run against
production. `data/global.db` is live with 536 feeds, 23965 entries, 7 `databases` rows, 550
`database_feeds`, 22349 `entry_status` rows, and 1 `user_prefs` row. The 7 databases: personal
(owner=downes) `rss`, `podcasts`, plus two not mentioned anywhere else in this doc —
`Cogdog_Podcasts`, `OpenEd_Podcasts`; public/collections (owner=NULL) `news`, `sessions`,
`technology`. Old `.db` files (`rss.db`, `Podcasts.db`, `news.db`, `sessions.db`, `technology.db`)
remain untouched on disk per house rule (never delete/overwrite a `.db` file without permission),
but the running app reads **only** `global.db` — see "Database" section above.

### Collections (rewritten 2026-11-02 — the per-slug `.db` file model below is gone, not "pending")
Predefined RSS collections, exposed publicly (no auth) for any CList instance to consume. They no
longer have their own SQLite files or scheduler loop — confirmed via `ensure_collections()`/
`_load_collection_manifests()` (`app.py:402-475`), they're just rows in the global schema:
- Manifests: bind-mounted JSON files under `./data/collections/manifests/*.json`, each `{"slug":
  "...", "title": "...", "feeds": [...]}`. Slug must match `^[A-Za-z0-9_-]+$` — unchanged.
- `ensure_collections()` upserts each manifest as a `databases` row with `owner_kvstore_url=NULL,
  owner_kvkey=NULL`, and its feeds into `database_feeds` (membership), all in `global.db` — not a
  separate `./data/collections/<slug>.db` file. It runs under `COLLECTIONS_WRITE_LOCK` (still a
  `threading.Lock`, same serialization purpose as before, now guarding writes to the shared global
  file rather than coordinating across many separate files) as one step inside the single unified
  `harvest_loop()` (see Background Scheduler below), not a scheduler loop of its own.
- Feed sync is still **add-only** (`INSERT OR IGNORE` into `database_feeds`) — editing a manifest
  never removes feeds from the collection.
- Public endpoints (CORS `Access-Control-Allow-Origin: *`, no credentials), unchanged:
  - `GET /api/collections` — list of `{slug, title, feed_count}`
  - `GET /api/collections/<slug>/items?limit=200` — ranked items from that collection
- To add a new collection: drop a manifest JSON file into `./data/collections/manifests/` — no
  restart required, picked up by `ensure_collections()` on the next harvest tick (or restart the
  container to pick it up immediately).

## Environment variables (set in `docker-compose.yml`, no `.env` file)
- `RSS_DB`                   — Path to the global SQLite DB file (default: /data/global.db, both
  the Dockerfile's `ENV` and the `docker-compose.yml` override now agree — fixed 2026-11-02).
- `RSS_PORT`                 — Internal port (default: 8787)
- `RSS_ALLOWED_KVSTORE_URLS` — Comma-separated kvstore instances trusted to vouch for an
  `ADMIN_USERNAMES` admin, and valid opaque/legacy-token fallback targets (named by a
  client's `X-Kvstore-Url` header) (default: https://kvstore.mooc.ca,https://kvstore.downes.ca)
  — fallback; overridden by `app_settings.RSS_ALLOWED_KVSTORE_URLS` once an admin saves one.
  Does NOT gate ordinary token verification, which is open to any issuer.
- `ADMIN_USERNAMES`          — Comma-separated kvstore usernames allowed to use `/admin/settings`

## Background Scheduler
One unified `harvest_loop()` over the global, deduplicated `feeds` table (the "Architecture:
Global Harvest Store" design above is live, not just proposed — `database_feeds`/
`resolve_database` are already in use). Replaces the old split `scheduler_loop()`/
`collections_scheduler_loop()`, which existed only because collections used to live in separate
DB files; writes are now serialized via `DB_WRITE_LOCK`/`COLLECTIONS_WRITE_LOCK` within one
process as before.

`start_background_scheduler()` runs at **module level** (not inside `if __name__ ==
"__main__":`), so it actually starts under gunicorn in production.

**Multi-worker leader election (added 2026-11-02):** the Dockerfile runs gunicorn with
`--workers 2` — two separate OS processes, each with its own GIL, so a CPU-bound harvest batch in
one worker no longer blocks HTTP handling in the other. (Fixed a real bug: Find/search was
stalling 20+ seconds on the first request after any idle period, because the single worker's GIL
was shared between the sync harvester thread and the Flask request thread.) Since module-level
code runs once per worker, `start_background_scheduler()` now calls
`_acquire_scheduler_leadership()` first, which takes an `fcntl.flock(LOCK_EX | LOCK_NB)` on a
`.harvester.lock` sentinel file in `/data` (bind-mounted, survives rebuilds). Whichever worker
gets the lock runs `harvest_loop()`; the other logs `"Another worker already owns the harvester;
not starting it here."` and skips it entirely, so feeds are never fetched twice in parallel. The
lock fd is held open in a module global for the worker's lifetime — if that worker process dies,
the OS releases the lock automatically and the other worker would pick it up on its next restart
(gunicorn doesn't currently re-run `start_background_scheduler()` on a worker respawn, so in
practice this means the harvester resumes after the *container* restarts, not after a single
worker crash — acceptable since `restart: always` + the 2-worker split already covers the
request-serving half of the original problem).

**Known gap (not yet fixed, logged in `/srv/TODO.md` 2026-11-02):** `/api/update_start` /
`/api/update_progress` (the admin "Update Now" button and its progress poll) still use in-process
globals (`_jobs`, `_active_job_id`), which aren't shared across the two workers and aren't gated
by the flock above. A manual trigger landing on the non-leader worker can run concurrently with
the background harvester, and a progress poll can land on the wrong worker and appear to lose the
job. Admin-only impact, no data-corruption risk (SQLite's own locking + the existing 30s busy
timeout still serialize writes) — real fix is moving job state out of in-memory globals into
something cross-process-visible.
