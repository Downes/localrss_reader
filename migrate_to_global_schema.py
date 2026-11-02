#!/usr/bin/env python3
"""
One-time migration: fold today's per-file SQLite DBs (personal rss.db/Podcasts.db,
collection news.db/sessions.db/technology.db) into the new global schema (Phase 2a,
see /srv/apps/localrss_reader/CLAUDE.md "Architecture: Global Harvest Store").

Safety:
- Every source DB is opened read-only (sqlite3 "mode=ro" URI) -- this script cannot
  write to rss.db, Podcasts.db, or any collection DB no matter what.
- Default mode is a dry run: the merge runs entirely against an in-memory target DB,
  nothing touches disk. Pass --execute to write a real file at --output.
- --execute refuses to overwrite an existing --output file unless --force is also given.

Usage:
    python3 migrate_to_global_schema.py                 # dry run, prints summary only
    python3 migrate_to_global_schema.py --execute        # writes data/global.db
    python3 migrate_to_global_schema.py --execute --output data/global.db --force
"""
import argparse
import json
import os
import sqlite3
import time

# --- CONFIRM BEFORE RUNNING FOR REAL -----------------------------------------------
OWNER_KVKEY = "downes"
OWNER_KVSTORE_URL = "https://kvstore.mooc.ca"  # confirmed 2026-10-31
# ------------------------------------------------------------------------------------

# Pre-migration "current database" pointer (old global-process-state model) -- used
# only to seed user_prefs below so the admin UI's db selector (which never auto-calls
# /api/db_select on first load if the server reports no "current" db) keeps working
# on the very first page load post-migration, with zero frontend changes.
LAST_DB_FILE = "data/.localrss_last_db.json"

SCHEMA = """
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
    feed_image    TEXT
);
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
    created_at   INTEGER NOT NULL,
    UNIQUE(feed_id, guid)
);
CREATE INDEX idx_entries_feed_pub ON entries(feed_id, published);
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
CREATE TABLE database_feeds (
    database_id INTEGER NOT NULL REFERENCES databases(id),
    feed_id     INTEGER NOT NULL REFERENCES feeds(id),
    added_at    INTEGER NOT NULL,
    PRIMARY KEY (database_id, feed_id)
);
CREATE TABLE entry_status (
    database_id INTEGER NOT NULL REFERENCES databases(id),
    entry_id    INTEGER NOT NULL REFERENCES entries(id),
    read_at     INTEGER,
    bookmarked  INTEGER DEFAULT 0,
    PRIMARY KEY (database_id, entry_id)
);
CREATE INDEX idx_entry_status_db_read ON entry_status(database_id, read_at);
CREATE INDEX idx_entry_status_db_bookmarked ON entry_status(database_id, bookmarked);
CREATE TABLE user_prefs (
    owner_kvstore_url TEXT NOT NULL,
    owner_kvkey       TEXT NOT NULL,
    database_id       INTEGER NOT NULL REFERENCES databases(id),
    PRIMARY KEY (owner_kvstore_url, owner_kvkey)
);
"""

# (source path, slug, title, owner) -- owner None => public/collection-style
SOURCES = [
    ("data/rss.db", "rss", "RSS", OWNER_KVKEY),
    ("data/Podcasts.db", "podcasts", "Podcasts", OWNER_KVKEY),
    ("data/collections/news.db", "news", "News", None),
    ("data/collections/sessions.db", "sessions", "Sessions", None),
    ("data/collections/technology.db", "technology", "Technology", None),
]

# Columns that don't exist on every source DB (see CLAUDE.md migration note:
# Podcasts.db predates these) -- select with a per-DB-detected column list instead
# of assuming every optional column is present.
FEEDS_OPTIONAL_COLS = ["error_msg", "feed_author", "feed_image"]
ENTRIES_OPTIONAL_COLS = ["author", "thumbnail"]


def open_source(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def existing_columns(con, table, candidates):
    cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    return [c for c in candidates if c in cols]


def get_or_create_database(target, slug, title, owner_kvkey):
    owner_url = OWNER_KVSTORE_URL if owner_kvkey else None
    # slug is scoped to the owner identity, not globally unique -- look up (and later
    # address) a database by the full (owner_kvstore_url, owner_kvkey, slug) tuple for
    # owned ones, or by slug alone among owner-less (public) ones.
    if owner_kvkey:
        row = target.execute(
            "SELECT id FROM databases WHERE owner_kvstore_url = ? AND owner_kvkey = ? AND slug = ?",
            (owner_url, owner_kvkey, slug),
        ).fetchone()
    else:
        row = target.execute(
            "SELECT id FROM databases WHERE owner_kvkey IS NULL AND slug = ?", (slug,)
        ).fetchone()
    if row:
        return row[0]
    cur = target.execute(
        "INSERT INTO databases (slug, title, owner_kvstore_url, owner_kvkey, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (slug, title, owner_url, owner_kvkey, int(time.time())),
    )
    return cur.lastrowid


def migrate_feeds(source, target, database_id):
    """Returns {source_feed_id: target_feed_id}, deduped globally by url."""
    opt_cols = existing_columns(source, "feeds", FEEDS_OPTIONAL_COLS)
    base_cols = ["id", "url", "title", "etag", "last_modified", "last_fetch",
                 "fail_count", "next_fetch", "month_count", "last_ok"]
    cols = base_cols + opt_cols
    id_map = {}
    for row in source.execute(f"SELECT {', '.join(cols)} FROM feeds"):
        vals = dict(zip(cols, row))
        for c in FEEDS_OPTIONAL_COLS:
            vals.setdefault(c, None)

        existing = target.execute(
            "SELECT id, last_fetch FROM feeds WHERE url = ?", (vals["url"],)
        ).fetchone()
        if existing is None:
            cur = target.execute(
                "INSERT INTO feeds (url, title, etag, last_modified, last_fetch, "
                "fail_count, next_fetch, month_count, last_ok, error_msg, "
                "feed_author, feed_image) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (vals["url"], vals["title"], vals["etag"], vals["last_modified"],
                 vals["last_fetch"], vals["fail_count"], vals["next_fetch"],
                 vals["month_count"], vals["last_ok"], vals["error_msg"],
                 vals["feed_author"], vals["feed_image"]),
            )
            target_feed_id = cur.lastrowid
        else:
            target_feed_id, existing_last_fetch = existing
            # Merge policy: the more recently-fetched source wins the metadata.
            if (vals["last_fetch"] or 0) > (existing_last_fetch or 0):
                target.execute(
                    "UPDATE feeds SET title=?, etag=?, last_modified=?, last_fetch=?, "
                    "fail_count=?, next_fetch=?, month_count=?, last_ok=?, error_msg=?, "
                    "feed_author=?, feed_image=? WHERE id=?",
                    (vals["title"], vals["etag"], vals["last_modified"], vals["last_fetch"],
                     vals["fail_count"], vals["next_fetch"], vals["month_count"],
                     vals["last_ok"], vals["error_msg"], vals["feed_author"],
                     vals["feed_image"], target_feed_id),
                )

        target.execute(
            "INSERT OR IGNORE INTO database_feeds (database_id, feed_id, added_at) "
            "VALUES (?, ?, ?)",
            (database_id, target_feed_id, int(time.time())),
        )
        id_map[vals["id"]] = target_feed_id
    return id_map


def migrate_entries(source, target, database_id, feed_id_map):
    """Dedupes entries globally by (feed_id, guid); every source row becomes exactly
    one entry_status row for this database, even when the entry itself already existed."""
    opt_cols = existing_columns(source, "entries", ENTRIES_OPTIONAL_COLS)
    base_cols = ["id", "feed_id", "guid", "title", "link", "published",
                 "content_html", "read_at", "bookmarked", "created_at"]
    cols = base_cols + opt_cols
    count = 0
    for row in source.execute(f"SELECT {', '.join(cols)} FROM entries"):
        vals = dict(zip(cols, row))
        for c in ENTRIES_OPTIONAL_COLS:
            vals.setdefault(c, None)

        target_feed_id = feed_id_map[vals["feed_id"]]
        existing = target.execute(
            "SELECT id FROM entries WHERE feed_id = ? AND guid = ?",
            (target_feed_id, vals["guid"]),
        ).fetchone()
        if existing is None:
            cur = target.execute(
                "INSERT INTO entries (feed_id, guid, title, link, author, published, "
                "content_html, thumbnail, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (target_feed_id, vals["guid"], vals["title"], vals["link"],
                 vals["author"], vals["published"], vals["content_html"],
                 vals["thumbnail"], vals["created_at"]),
            )
            target_entry_id = cur.lastrowid
        else:
            target_entry_id = existing[0]

        target.execute(
            "INSERT OR REPLACE INTO entry_status (database_id, entry_id, read_at, bookmarked) "
            "VALUES (?, ?, ?, ?)",
            (database_id, target_entry_id, vals["read_at"], vals["bookmarked"]),
        )
        count += 1
    return count


def seed_user_pref(target, fallback_slug="rss"):
    """Point OWNER_KVKEY's user_prefs row at whatever database was 'current' per
    the pre-migration .localrss_last_db.json (falling back to fallback_slug if
    that file is missing/unreadable or names a database that wasn't migrated).
    Without this, the admin UI's db selector shows no 'current' value and never
    auto-calls /api/db_select, so Stephen -- who owns two personal databases, not
    one -- would hit an "ambiguous, pick one" error on the very first page load
    after cutover."""
    slug = fallback_slug
    try:
        with open(LAST_DB_FILE) as f:
            last_db_abs = json.load(f).get("last_db_abs") or ""
        slug = os.path.splitext(os.path.basename(last_db_abs))[0] or fallback_slug
    except Exception:
        pass

    row = target.execute(
        "SELECT id FROM databases WHERE owner_kvstore_url=? AND owner_kvkey=? AND slug=?",
        (OWNER_KVSTORE_URL, OWNER_KVKEY, slug),
    ).fetchone()
    if not row and slug != fallback_slug:
        slug = fallback_slug
        row = target.execute(
            "SELECT id FROM databases WHERE owner_kvstore_url=? AND owner_kvkey=? AND slug=?",
            (OWNER_KVSTORE_URL, OWNER_KVKEY, slug),
        ).fetchone()
    if not row:
        print(f"[WARN] Could not seed user_prefs: no migrated database named '{slug}' for {OWNER_KVKEY}")
        return
    target.execute(
        "INSERT OR REPLACE INTO user_prefs (owner_kvstore_url, owner_kvkey, database_id) VALUES (?, ?, ?)",
        (OWNER_KVSTORE_URL, OWNER_KVKEY, row[0]),
    )
    print(f"user_prefs seeded: current database = '{slug}'")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="data/global.db")
    ap.add_argument("--execute", action="store_true",
                     help="Actually write --output. Without this, runs entirely in-memory.")
    ap.add_argument("--force", action="store_true",
                     help="Allow overwriting an existing --output file.")
    args = ap.parse_args()

    if args.execute:
        import os
        if os.path.exists(args.output):
            if not args.force:
                raise SystemExit(f"{args.output} already exists -- pass --force to overwrite")
            os.remove(args.output)
        target = sqlite3.connect(args.output)
    else:
        target = sqlite3.connect(":memory:")

    target.executescript(SCHEMA)

    source_entry_totals = 0
    for path, slug, title, owner in SOURCES:
        source = open_source(path)
        database_id = get_or_create_database(target, slug, title, owner)
        feed_id_map = migrate_feeds(source, target, database_id)
        n_entries = migrate_entries(source, target, database_id, feed_id_map)
        source_entry_totals += n_entries
        print(f"{slug:12s} feeds={len(feed_id_map):5d}  entries={n_entries:6d}")
        source.close()

    seed_user_pref(target)

    target.commit()
    total_feeds = target.execute("SELECT COUNT(*) FROM feeds").fetchone()[0]
    total_entries = target.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    total_status = target.execute("SELECT COUNT(*) FROM entry_status").fetchone()[0]
    print("---")
    print(f"global feeds (deduped):  {total_feeds}")
    print(f"global entries (deduped): {total_entries}")
    print(f"entry_status rows:        {total_status}  (should equal sum of source entries: {source_entry_totals})")
    if total_status != source_entry_totals:
        print("MISMATCH -- status row count does not match source entry count, investigate before trusting this run")
    print("EXECUTED (file written)" if args.execute else "DRY RUN (nothing written to disk)")


if __name__ == "__main__":
    main()
