import asyncio
import calendar
import hashlib
import re
import os
import sys
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from math import exp
import io
import json
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from urllib.parse import urljoin
from html.parser import HTMLParser

import aiohttp
import feedparser
from flask import Flask, g, jsonify, request, send_from_directory, Response

from admin_settings import (
    SettingField,
    init_settings_table,
    get_setting,
    register_admin_settings_routes,
)

# -----------------------
# Config
# -----------------------
# RSS_DB is the "default" DB path. On startup, the app will scan the DB directory
# for *.db files and select the most recently used DB (persisted), or otherwise
# the first DB in the directory list.
CONFIG_DB_PATH = os.environ.get("RSS_DB", "rss.db")
DB_PATH = CONFIG_DB_PATH  # will be overridden by startup selection below
DB_PATH_ABS = os.path.abspath(DB_PATH)
ACTIVE_DB_PATH = DB_PATH_ABS

DB_DIR = os.path.dirname(os.path.abspath(CONFIG_DB_PATH)) or os.path.abspath(".")
LAST_DB_FILE = os.path.join(DB_DIR, ".localrss_last_db.json")

PORT = int(os.environ.get("RSS_PORT", "8787"))
APP_VERSION = "0.4.15"
USER_AGENT = os.environ.get("RSS_UA", f"LocalRSSReader/{APP_VERSION} (+Windows; local)")
MAX_CONCURRENCY = int(os.environ.get("RSS_CONCURRENCY", "40"))
LIMIT_PER_HOST = int(os.environ.get("RSS_LIMIT_PER_HOST", "4"))


def _scan_databases() -> list[str]:
    try:
        if not os.path.exists(DB_DIR):
            os.makedirs(DB_DIR, exist_ok=True)
    except Exception:
        pass

    dbs = []
    try:
        for name in os.listdir(DB_DIR):
            if name.lower().endswith(".db") and os.path.isfile(os.path.join(DB_DIR, name)):
                dbs.append(name)
    except Exception:
        return []
    dbs.sort(key=lambda s: s.lower())
    return dbs


def _load_last_db_abs() -> str | None:
    try:
        if not os.path.exists(LAST_DB_FILE):
            return None
        with open(LAST_DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        p = (data or {}).get("last_db_abs")
        if not p:
            return None
        return os.path.abspath(p)
    except Exception:
        return None


def _save_last_db_abs(db_abs: str) -> None:
    try:
        tmp = {"last_db_abs": os.path.abspath(db_abs)}
        with open(LAST_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(tmp, f)
    except Exception:
        pass


def _set_current_db_abs(db_abs: str) -> None:
    """Set the app's current DB (absolute path) and persist as most recently used."""
    global DB_PATH, DB_PATH_ABS, ACTIVE_DB_PATH
    DB_PATH = os.path.abspath(db_abs)
    DB_PATH_ABS = os.path.abspath(DB_PATH)
    ACTIVE_DB_PATH = DB_PATH_ABS
    _save_last_db_abs(DB_PATH_ABS)


def _select_startup_db() -> None:
    # candidate list comes from the configured DB directory
    dbs = _scan_databases()
    last_abs = _load_last_db_abs()
    if last_abs:
        last_name = os.path.basename(last_abs)
        if last_name in dbs and os.path.abspath(os.path.join(DB_DIR, last_name)) == last_abs:
            _set_current_db_abs(last_abs)
            return

    if dbs:
        _set_current_db_abs(os.path.join(DB_DIR, dbs[0]))
        return

    # No *.db files in directory: keep configured default
    _set_current_db_abs(os.path.abspath(CONFIG_DB_PATH))


# Choose DB at import/startup time
_select_startup_db()
RETENTION_DAYS = int(os.environ.get("RSS_RETENTION_DAYS", "30"))

# Feeds this broken are almost certainly dead/misconfigured - stop burning
# scheduler cycles on them until a human edits or manually retries the feed.
MAX_FEED_FAIL_COUNT = int(os.environ.get("RSS_MAX_FEED_FAIL_COUNT", "50"))

SCHEDULER_TICK_SECONDS = int(os.environ.get("RSS_TICK", "60"))
SQLITE_TIMEOUT = float(os.environ.get("RSS_SQLITE_TIMEOUT", "30"))

INTERVAL_LOW = int(os.environ.get("RSS_INTERVAL_LOW", str(20 * 60)))
INTERVAL_MED = int(os.environ.get("RSS_INTERVAL_MED", str(60 * 60)))
INTERVAL_HIGH = int(os.environ.get("RSS_INTERVAL_HIGH", str(2 * 60 * 60)))

# kvstore login gate: every route except "/", "/static/*", and "/api/collections*"
# requires a Bearer token verified against the kvstore instance named in the
# client's X-Kvstore-Url header (must be one of the allowed kvstore URLs, see
# _allowed_kvstore_urls() below). RSS_ALLOWED_KVSTORE_URLS (.env) is the
# fallback; an admin override saved via /admin/settings takes effect
# immediately, no restart.
RSS_ALLOWED_KVSTORE_URLS_DEFAULT = os.environ.get(
    "RSS_ALLOWED_KVSTORE_URLS", "https://kvstore.mooc.ca,https://kvstore.downes.ca"
)

# Collections: predefined, file-based bundles of feeds harvested independently
# of any personal DB and exposed read-only, unauthenticated, under /api/collections.
COLLECTIONS_DIR = os.path.join(DB_DIR, "collections")
COLLECTIONS_MANIFEST_DIR = os.path.join(COLLECTIONS_DIR, "manifests")

# Admin-editable runtime settings live in their own DB file, independent of
# the switchable personal DBs (rss.db, Podcasts.db, ...) — switching which
# personal DB is "active" must never make admin settings appear to reset.
ADMIN_SETTINGS_DB_PATH = os.path.join(DB_DIR, "admin_settings.db")

# -----------------------
# App
# -----------------------
app = Flask(__name__, static_folder="static")

def now_ts() -> int:
    return int(time.time())

def cutoff_ts(days: int = RETENTION_DAYS) -> int:
    return int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())

# Serialize *all* write operations to avoid "database is locked"
DB_WRITE_LOCK = threading.Lock()

def connect_db() -> sqlite3.Connection:
    """
    Connect to SQLite database.
    - Re-reads the persisted DB selection on every connect so all Gunicorn
      workers stay in sync when the user switches databases.
    - If RSS_DB points to a path whose directory doesn't exist, create it.
    - If the path cannot be opened, fall back to a local rss.db next to app.py,
      so the app stays up (with an empty/new DB) instead of crashing.
    """
    global ACTIVE_DB_PATH, DB_PATH, DB_PATH_ABS

    # Re-read persisted selection so multi-worker Gunicorn stays in sync
    last_abs = _load_last_db_abs()
    if last_abs and os.path.exists(last_abs):
        DB_PATH = last_abs
        DB_PATH_ABS = last_abs
        ACTIVE_DB_PATH = last_abs

    db_abs = os.path.abspath(DB_PATH)
    parent = os.path.dirname(db_abs)
    if parent and not os.path.exists(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except Exception as e:
            print(f"[WARN] Could not create DB directory '{parent}': {e}", file=sys.stderr)

    try:
        con = sqlite3.connect(db_abs, timeout=SQLITE_TIMEOUT)
        ACTIVE_DB_PATH = db_abs
        _save_last_db_abs(ACTIVE_DB_PATH)
        con.row_factory = sqlite3.Row
        return con
    except Exception as e:
        fallback_abs = os.path.abspath(os.path.join(os.path.dirname(__file__), "rss.db"))
        try:
            con = sqlite3.connect(fallback_abs, timeout=SQLITE_TIMEOUT)
            ACTIVE_DB_PATH = fallback_abs
            _save_last_db_abs(ACTIVE_DB_PATH)
            con.row_factory = sqlite3.Row
            print(f"[WARN] Could not open DB at '{db_abs}' ({e}). Falling back to '{fallback_abs}'.", file=sys.stderr)
            return con
        except Exception as e2:
            raise RuntimeError(
                f"Unable to open database file. Tried '{db_abs}' and fallback '{fallback_abs}'. Error: {e2}"
            ) from e2


def connect_db_at(db_path: str) -> sqlite3.Connection:
    """Connect directly to an explicit DB path, bypassing connect_db()'s
    global active-DB state. Used for collection DBs, which are independent
    files with no relationship to the personal "active" database."""
    db_abs = os.path.abspath(db_path)
    parent = os.path.dirname(db_abs)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    con = sqlite3.connect(db_abs, timeout=SQLITE_TIMEOUT)
    con.row_factory = sqlite3.Row
    return con


def _apply_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
    CREATE TABLE IF NOT EXISTS feeds (
      id INTEGER PRIMARY KEY,
      url TEXT NOT NULL UNIQUE,
      title TEXT,
      etag TEXT,
      last_modified TEXT,
      last_fetch INTEGER,
      fail_count INTEGER DEFAULT 0,
      next_fetch INTEGER DEFAULT 0,
      month_count INTEGER DEFAULT 0,
      last_ok INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS entries (
      id INTEGER PRIMARY KEY,
      feed_id INTEGER NOT NULL,
      guid TEXT NOT NULL,
      title TEXT,
      link TEXT,
      author TEXT,
      published INTEGER,
      content_html TEXT,
      read_at INTEGER,
      bookmarked INTEGER DEFAULT 0,
      created_at INTEGER NOT NULL,
      UNIQUE(feed_id, guid),
      FOREIGN KEY(feed_id) REFERENCES feeds(id)
    );

    CREATE INDEX IF NOT EXISTS idx_entries_unread ON entries(read_at);
    CREATE INDEX IF NOT EXISTS idx_entries_bookmarked ON entries(bookmarked);
    CREATE INDEX IF NOT EXISTS idx_entries_feed_pub ON entries(feed_id, published);
    """)
    con.commit()
    for stmt in (
        "ALTER TABLE feeds ADD COLUMN error_msg TEXT",
        "ALTER TABLE entries ADD COLUMN author TEXT",
        "ALTER TABLE entries ADD COLUMN thumbnail TEXT",
        "ALTER TABLE feeds ADD COLUMN feed_author TEXT",
        "ALTER TABLE feeds ADD COLUMN feed_image TEXT",
    ):
        try:
            con.execute(stmt)
            con.commit()
        except Exception:
            pass


def init_db():
    con = connect_db()
    _apply_schema(con)
    con.close()
    settings_con = connect_db_at(ADMIN_SETTINGS_DB_PATH)
    init_settings_table(settings_con)
    settings_con.close()

def _sanitize_db_name(name: str) -> str:
    # Keep only a conservative set of characters for filenames
    name = (name or "").strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    if not name:
        return ""
    if not name.lower().endswith(".db"):
        name += ".db"
    return name


def _looks_like_feed(content_type: str | None, body: bytes) -> bool:
    """Best-effort check: does this response look like RSS/Atom XML?"""
    ct = (content_type or "").lower()
    if any(t in ct for t in ("application/rss+xml", "application/atom+xml", "application/xml", "text/xml")):
        return True
    # Sniff body
    head = body[:4096].lstrip()
    # XML declaration or feed tags
    if head.startswith(b"<?xml"):
        return True
    lower = head.lower()
    return (b"<rss" in lower) or (b"<feed" in lower and b"xmlns" in lower)


class _HeadLinkFinder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.candidates: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "head":
            self.in_head = True
            return
        if not self.in_head:
            return
        if tag.lower() != "link":
            return
        d = {k.lower(): (v or "") for (k, v) in attrs}
        rel = d.get("rel", "").lower()
        typ = d.get("type", "").lower()
        href = d.get("href", "")
        if not href:
            return
        if "alternate" not in rel:
            return
        if "rss" in typ or "atom" in typ or "xml" in typ:
            self.candidates.append(href)

    def handle_endtag(self, tag):
        if tag.lower() == "head":
            self.in_head = False


def _fetch_url_bytes(url: str, timeout: int = 12) -> tuple[bytes, str | None]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.8",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ct = resp.headers.get("Content-Type")
        body = resp.read()
        return body, ct


def discover_feed_url(input_url: str) -> tuple[str, str]:
    """Return (feed_url, kind) where kind is 'direct' or 'discovered'. Raises ValueError."""
    url = (input_url or "").strip()
    if not url:
        raise ValueError("URL is required")
    if not re.match(r"^https?://", url, re.I):
        raise ValueError("URL must start with http:// or https://")

    body, ct = _fetch_url_bytes(url)
    if _looks_like_feed(ct, body):
        return url, "direct"

    # Parse HTML head for RSS/Atom link
    try:
        text = body.decode("utf-8", errors="ignore")
    except Exception:
        text = ""
    parser = _HeadLinkFinder()
    parser.feed(text)
    if not parser.candidates:
        raise ValueError("No RSS/Atom link tag found in the page header.")

    # Choose first candidate (site may expose multiple)
    feed_url = urljoin(url, parser.candidates[0])
    return feed_url, "discovered"

def _parse_opml(xml_bytes: bytes):
    """Return list of (url, title) from an OPML file."""
    try:
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        raise ValueError(f"Invalid OPML/XML: {e}")

    pairs = []
    seen = set()
    for el in root.findall(".//outline"):
        url = el.attrib.get("xmlUrl") or el.attrib.get("xmlurl") or el.attrib.get("url")
        if not url:
            continue
        url = url.strip()
        if not url or url in seen:
            continue
        title = (el.attrib.get("title") or el.attrib.get("text") or "").strip() or None
        pairs.append((url, title))
        seen.add(url)
    return pairs

def _build_opml(feeds):
    now_iso = datetime.now().strftime("%a, %d %b %Y %H:%M:%S")
    parts = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append('<opml version="2.0">')
    parts.append('  <head>')
    parts.append('    <title>LocalRSSReader Feeds</title>')
    parts.append(f'    <dateCreated>{now_iso}</dateCreated>')
    parts.append('  </head>')
    parts.append('  <body>')
    for f in feeds:
        url = (f["url"] if isinstance(f, dict) else f[0]) or ""
        title = (f["title"] if isinstance(f, dict) else (f[1] if len(f) > 1 else None)) or url
        # minimal XML escaping
        def esc(s): 
            return (s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;"))
        parts.append(f'    <outline type="rss" text="{esc(title)}" title="{esc(title)}" xmlUrl="{esc(url)}" />')
    parts.append('  </body>')
    parts.append('</opml>')
    return "\n".join(parts).encode("utf-8")


def get_db():
    if "db" not in g:
        g.db = connect_db()
    return g.db

def get_admin_settings_db() -> sqlite3.Connection:
    if "admin_settings_db" not in g:
        g.admin_settings_db = connect_db_at(ADMIN_SETTINGS_DB_PATH)
    return g.admin_settings_db

@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()
    admin_settings_db = g.pop("admin_settings_db", None)
    if admin_settings_db is not None:
        admin_settings_db.close()

def ensure_feed(db, url: str):
    db.execute("INSERT OR IGNORE INTO feeds(url, next_fetch) VALUES(?, ?)", (url, 0))

# -----------------------
# Collections (public, unauthenticated, read-only feed bundles)
# -----------------------
# Serializes writes to collection DBs. Separate from DB_WRITE_LOCK since
# collection DBs are different files with no real contention against the
# personal DB.
COLLECTIONS_WRITE_LOCK = threading.Lock()

def _collection_db_path(slug: str) -> str:
    return os.path.join(COLLECTIONS_DIR, f"{slug}.db")

def _load_collection_manifests() -> list[dict]:
    """Scan COLLECTIONS_MANIFEST_DIR for {"slug", "title", "feeds"} JSON files.
    Skips and logs malformed manifests rather than failing the whole scan."""
    manifests = []
    try:
        os.makedirs(COLLECTIONS_MANIFEST_DIR, exist_ok=True)
        names = sorted(os.listdir(COLLECTIONS_MANIFEST_DIR))
    except Exception as e:
        print(f"[WARN] Could not scan collections manifest dir: {e}", file=sys.stderr)
        return manifests

    for name in names:
        if not name.lower().endswith(".json"):
            continue
        path = os.path.join(COLLECTIONS_MANIFEST_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            slug = (data.get("slug") or "").strip()
            title = (data.get("title") or "").strip()
            feeds = data.get("feeds") or []
            if not re.match(r"^[A-Za-z0-9_-]+$", slug):
                print(f"[WARN] Collection manifest '{name}' has invalid/missing slug, skipping.", file=sys.stderr)
                continue
            if not title or not isinstance(feeds, list):
                print(f"[WARN] Collection manifest '{name}' missing title or feeds list, skipping.", file=sys.stderr)
                continue
            manifests.append({
                "slug": slug,
                "title": title,
                "feeds": [str(u).strip() for u in feeds if str(u).strip()],
            })
        except Exception as e:
            print(f"[WARN] Could not load collection manifest '{name}': {e}", file=sys.stderr)
    return manifests

def _init_collection_db(db_path: str) -> None:
    con = connect_db_at(db_path)
    try:
        _apply_schema(con)
    finally:
        con.close()

def _sync_collection_feeds(db_path: str, feed_urls: list[str]) -> None:
    """Add-only sync: ensures every feed in the manifest exists in the DB.
    Never removes a feed, so a manifest temporarily dropping a URL doesn't
    discard that feed's harvested history."""
    con = connect_db_at(db_path)
    try:
        for url in feed_urls:
            ensure_feed(con, url)
        con.commit()
    finally:
        con.close()

def ensure_collections() -> list[dict]:
    """Idempotent: creates each collection's DB if missing and syncs its feed
    list. Caller is responsible for holding COLLECTIONS_WRITE_LOCK."""
    manifests = _load_collection_manifests()
    for m in manifests:
        db_path = _collection_db_path(m["slug"])
        if not os.path.exists(db_path):
            _init_collection_db(db_path)
        _sync_collection_feeds(db_path, m["feeds"])
    return manifests

def stable_guid(entry) -> str:
    gid = entry.get("id") or entry.get("guid")
    if gid:
        return str(gid)
    link = entry.get("link", "")
    title = entry.get("title", "")
    published = str(entry.get("published", "")) or str(entry.get("updated", ""))
    raw = f"{link}\n{title}\n{published}".encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()

def safe_struct_time_to_ts(st) -> int:
    """
    Convert a time.struct_time-like object to epoch seconds safely on Windows.
    Some feeds contain absurd years (e.g. 0001 or 9999), which can crash time.mktime().
    """
    try:
        y = int(st.tm_year)
        # Windows mktime often fails outside ~1970-2038; clamp aggressively.
        now_year = datetime.now(timezone.utc).year
        if y < 1971 or y > now_year + 5:
            return now_ts()
    except Exception:
        return now_ts()

    # Prefer UTC conversion if possible (avoids local DST issues)
    try:
        return int(calendar.timegm(st))
    except Exception:
        pass

    # Fallback to local mktime (can still fail)
    try:
        return int(time.mktime(st))
    except Exception:
        return now_ts()

def entry_published_ts(entry) -> int:
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            return safe_struct_time_to_ts(st)
    return now_ts()

def entry_content_html(entry) -> str:
    if entry.get("content"):
        try:
            return entry["content"][0].get("value") or ""
        except Exception:
            pass
    return entry.get("summary", "") or ""

def entry_thumbnail(entry) -> str | None:
    """Best-effort feed-supplied thumbnail: media:thumbnail, media:content
    (image), an image enclosure, or itunes:image - in that order. Only looks
    at data feedparser already parsed from the feed, no extra fetch."""
    media_thumb = entry.get("media_thumbnail")
    if media_thumb:
        url = media_thumb[0].get("url")
        if url:
            return url
    for m in (entry.get("media_content") or []):
        if m.get("medium") == "image" or (m.get("type") or "").startswith("image/"):
            if m.get("url"):
                return m.get("url")
    for enc in (entry.get("enclosures") or []):
        if (enc.get("type") or "").startswith("image/") and enc.get("href"):
            return enc.get("href")
    image = entry.get("image")
    if image and image.get("href"):
        return image.get("href")
    return None

def feed_level_author(feed) -> str | None:
    """Best-effort feed-supplied author name: Atom/RSS author, iTunes
    podcast author, or publisher - in that order."""
    author = (feed.get("author") or "").strip()
    if author:
        return author
    name = ((feed.get("author_detail") or {}).get("name") or "").strip()
    if name:
        return name
    publisher = (feed.get("publisher") or "").strip()
    if publisher:
        return publisher
    return None

def feed_level_image(feed) -> str | None:
    """Best-effort feed-supplied image/thumbnail: RSS <image>, iTunes
    podcast artwork, or Atom logo/icon - in that order."""
    href = ((feed.get("image") or {}).get("href") or "").strip()
    if href:
        return href
    logo = (feed.get("logo") or "").strip()
    if logo:
        return logo
    icon = (feed.get("icon") or "").strip()
    if icon:
        return icon
    return None

def recompute_month_count(db, feed_id: int, cutoff: int):
    row = db.execute(
        "SELECT COUNT(*) AS c FROM entries WHERE feed_id=? AND published>=?",
        (feed_id, cutoff)
    ).fetchone()
    c = int(row["c"])
    db.execute("UPDATE feeds SET month_count=? WHERE id=?", (c, feed_id))

def post_score(published_ts: int, month_count: int, now: int) -> float:
    """Rank score for a post: favours infrequent feeds and recent posts.
    Higher score = show first. Uses feed's 30-day post count and exponential
    freshness decay so low-volume feeds aren't buried by high-volume ones."""
    r = max(float(month_count or 0), 0.25)   # posts per ~30 days, floor 0.25
    age_days = max((now - published_ts) / 86400.0, 0.0)
    feed_weight = 1.0 / ((r + 1.0) ** 0.7)
    freshness = exp(-0.22 * age_days)
    return feed_weight * freshness


def choose_interval(month_count: int) -> int:
    if month_count <= 10:
        return INTERVAL_LOW
    if month_count <= 200:
        return INTERVAL_MED
    return INTERVAL_HIGH

# -----------------------
# Update core (async)
# -----------------------
async def fetch_one(session: aiohttp.ClientSession, sem: asyncio.Semaphore, feed_row):
    feed_id = feed_row["id"]
    url = feed_row["url"]
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if feed_row["etag"]:
        headers["If-None-Match"] = feed_row["etag"]
    if feed_row["last_modified"]:
        headers["If-Modified-Since"] = feed_row["last_modified"]

    async with sem:
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                status = resp.status
                if status == 304:
                    return (feed_id, "not_modified", None, None, None)
                if status != 200:
                    return (feed_id, "http_error", status, None, None)
                text = await resp.text(errors="ignore")
                etag = resp.headers.get("ETag")
                last_mod = resp.headers.get("Last-Modified")
                return (feed_id, "ok", text, etag, last_mod)
        except Exception as e:
            return (feed_id, "exception", str(e), None, None)

async def update_feeds_async(feed_ids=None, only_due=True, progress_cb=None, cancel_event: threading.Event | None = None, db_path: str | None = None):
    # IMPORTANT: callers should hold DB_WRITE_LOCK (personal DB) or
    # COLLECTIONS_WRITE_LOCK (db_path given) before calling this.
    db = connect_db_at(db_path) if db_path else connect_db()
    cutoff = cutoff_ts()

    if feed_ids:
        q = "SELECT * FROM feeds WHERE id IN (%s)" % ",".join("?" * len(feed_ids))
        feeds = db.execute(q, feed_ids).fetchall()
    else:
        if only_due:
            feeds = db.execute(
                "SELECT * FROM feeds WHERE next_fetch <= ? AND fail_count < ?",
                (now_ts(), MAX_FEED_FAIL_COUNT)
            ).fetchall()
        else:
            feeds = db.execute("SELECT * FROM feeds").fetchall()

    total = len(feeds)
    checked = updated = errors = 0

    if progress_cb:
        progress_cb(total=total, checked=0, updated=0, errors=0, state="running", current_url=None)

    if total == 0:
        db.close()
        return {"checked": 0, "updated": 0, "errors": 0, "total": 0}

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENCY, limit_per_host=LIMIT_PER_HOST, ttl_dns_cache=300)

    db.execute("BEGIN")
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            for f in feeds:
                if cancel_event and cancel_event.is_set():
                    break
                tasks.append(asyncio.create_task(fetch_one(session, sem, f)))

            for coro in asyncio.as_completed(tasks):
                if cancel_event and cancel_event.is_set():
                    break

                (feed_id, kind, payload, etag, last_mod) = await coro
                checked += 1

                urow = db.execute("SELECT url FROM feeds WHERE id=?", (feed_id,)).fetchone()
                cur_url = urow["url"] if urow else None

                try:
                    if kind == "not_modified":
                        mcrow = db.execute("SELECT month_count FROM feeds WHERE id=?", (feed_id,)).fetchone()
                        mc = int(mcrow["month_count"] or 0) if mcrow else 0
                        db.execute(
                            "UPDATE feeds SET last_fetch=?, fail_count=0, next_fetch=?, error_msg=NULL WHERE id=?",
                            (now_ts(), now_ts() + choose_interval(mc), feed_id)
                        )
                    elif kind != "ok":
                        errors += 1
                        row = db.execute("SELECT fail_count FROM feeds WHERE id=?", (feed_id,)).fetchone()
                        fail = int(row["fail_count"] or 0) + 1
                        backoff = min(6 * 3600, (2 ** min(fail, 8)) * 60)
                        if kind == "http_error":
                            error_msg = f"HTTP {payload}"
                        else:
                            error_msg = (str(payload) or "Connection error")[:500]
                        db.execute(
                            "UPDATE feeds SET last_fetch=?, fail_count=?, next_fetch=?, error_msg=? WHERE id=?",
                            (now_ts(), fail, now_ts() + backoff, error_msg, feed_id)
                        )
                    else:
                        # Parse & insert. Any weird entry dates should not crash the whole job.
                        parsed = feedparser.parse(payload)
                        feed_title = (parsed.feed.get("title") or "").strip() or None
                        f_author = feed_level_author(parsed.feed)
                        f_image = feed_level_image(parsed.feed)
                        db.execute(
                            """UPDATE feeds SET title=COALESCE(?, title),
                                 feed_author=COALESCE(feed_author, ?),
                                 feed_image=COALESCE(feed_image, ?),
                                 etag=?, last_modified=?, last_fetch=?, last_ok=?, fail_count=0, error_msg=NULL
                               WHERE id=?""",
                            (feed_title, f_author, f_image, etag, last_mod, now_ts(), now_ts(), feed_id)
                        )

                        added_any = False
                        for e in parsed.entries:
                            if cancel_event and cancel_event.is_set():
                                break
                            try:
                                guid = stable_guid(e)
                                title = (e.get("title") or "").strip()
                                link = e.get("link")
                                author = (e.get("author") or "").strip() or None
                                pub_ts = entry_published_ts(e)
                                if pub_ts < cutoff:
                                    continue
                                html = entry_content_html(e)
                                thumb = entry_thumbnail(e)
                                cur_ins = db.execute("""
                                  INSERT OR IGNORE INTO entries(feed_id,guid,title,link,author,published,content_html,thumbnail,created_at)
                                  VALUES(?,?,?,?,?,?,?,?,?)
                                """, (feed_id, guid, title, link, author, pub_ts, html, thumb, now_ts()))
                                if cur_ins.rowcount:
                                    added_any = True
                            except Exception:
                                errors += 1
                                continue

                        if added_any:
                            updated += 1

                        recompute_month_count(db, feed_id, cutoff)
                        mcrow = db.execute("SELECT month_count FROM feeds WHERE id=?", (feed_id,)).fetchone()
                        mc = int(mcrow["month_count"] or 0) if mcrow else 0
                        db.execute("UPDATE feeds SET next_fetch=? WHERE id=?", (now_ts() + choose_interval(mc), feed_id))
                except Exception:
                    # Treat any per-feed crash as an error, keep going.
                    errors += 1

                if progress_cb:
                    progress_cb(total=total, checked=checked, updated=updated, errors=errors, state="running", current_url=cur_url)

        db.execute("DELETE FROM entries WHERE published < ? AND bookmarked = 0", (cutoff,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return {"checked": checked, "updated": updated, "errors": errors, "total": total}

# -----------------------
# Job manager
# -----------------------
_jobs_lock = threading.Lock()
_jobs = {}
_active_job_id = None

def _new_job_id() -> str:
    return f"job_{now_ts()}_{os.getpid()}"

def _progress_updater(job_id: str, **kwargs):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(kwargs)
        job["last_change_ts"] = now_ts()

def start_update_job(full_sweep: bool = True) -> str:
    global _active_job_id
    with _jobs_lock:
        if _active_job_id and _jobs.get(_active_job_id, {}).get("state") == "running":
            return _active_job_id

        job_id = _new_job_id()
        cancel_event = threading.Event()
        _jobs[job_id] = {
            "state": "running",
            "checked": 0,
            "updated": 0,
            "errors": 0,
            "total": 0,
            "current_url": None,
            "started_ts": now_ts(),
            "last_change_ts": now_ts(),
            "_cancel_event": cancel_event,
        }
        _active_job_id = job_id

    def runner():
        try:
            def cb(**k):
                _progress_updater(job_id, **k)

            with DB_WRITE_LOCK:
                stats = asyncio.run(update_feeds_async(only_due=not full_sweep, progress_cb=cb, cancel_event=cancel_event))

            with _jobs_lock:
                job = _jobs.get(job_id)
                if job:
                    job.update(stats)
                    job["state"] = "cancelled" if cancel_event.is_set() else "done"
                    job["ended_ts"] = now_ts()
        except Exception as e:
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job:
                    job["state"] = "error"
                    job["error"] = str(e)
                    job["ended_ts"] = now_ts()

    threading.Thread(target=runner, daemon=True).start()
    return job_id

def cancel_update_job(job_id: str) -> bool:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return False
        ev = job.get("_cancel_event")
        if ev and hasattr(ev, "set"):
            ev.set()
            job["state"] = "cancelling"
            job["last_change_ts"] = now_ts()
            return True
        return False

def get_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        out = {k: v for k, v in job.items() if k != "_cancel_event"}
        out["job_id"] = job_id
        return out


def _any_update_job_running() -> bool:
    """True if an update job is currently running (manual or scheduler)."""
    with _jobs_lock:
        if not _active_job_id:
            return False
        job = _jobs.get(_active_job_id)
        return bool(job and job.get("state") == "running")

# -----------------------
# Background scheduler
# -----------------------
_scheduler_enabled = True

async def scheduler_loop():
    while True:
        await asyncio.sleep(SCHEDULER_TICK_SECONDS)
        if not _scheduler_enabled:
            continue
        acquired = DB_WRITE_LOCK.acquire(blocking=False)
        if not acquired:
            continue
        try:
            await update_feeds_async(only_due=True)
        except Exception:
            pass
        finally:
            DB_WRITE_LOCK.release()

async def collections_scheduler_loop():
    while True:
        await asyncio.sleep(SCHEDULER_TICK_SECONDS)
        acquired = COLLECTIONS_WRITE_LOCK.acquire(blocking=False)
        if not acquired:
            continue
        try:
            manifests = ensure_collections()
            for m in manifests:
                try:
                    await update_feeds_async(only_due=True, db_path=_collection_db_path(m["slug"]))
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            COLLECTIONS_WRITE_LOCK.release()

def start_background_scheduler():
    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.create_task(scheduler_loop())
        loop.create_task(collections_scheduler_loop())
        loop.run_forever()
    threading.Thread(target=runner, daemon=True).start()

# -----------------------
# Auth (kvstore login gate)
# -----------------------
_PUBLIC_PATHS = {"/"}
_PUBLIC_PATH_PREFIXES = ("/static/", "/api/collections")

def _allowed_kvstore_urls() -> list[str]:
    # Read fresh on every call so an admin override saved via /admin/settings
    # takes effect immediately, no restart.
    raw = get_setting(
        get_admin_settings_db(), "RSS_ALLOWED_KVSTORE_URLS",
        default=RSS_ALLOWED_KVSTORE_URLS_DEFAULT,
    )
    return [u.strip() for u in raw.split(",") if u.strip()]

def verify_token(req) -> tuple[str | None, tuple[dict, int] | None]:
    """Verify Bearer token against the kvstore instance named in the client's
    X-Kvstore-Url header (must be one of _allowed_kvstore_urls()).
    Returns (username, None) on success or (None, (body, status)) on failure."""
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, ({"error": "Missing or invalid Authorization header"}, 401)
    token = auth[7:].strip()

    kvstore_url = (req.headers.get("X-Kvstore-Url") or "").strip().rstrip("/")
    if not kvstore_url or kvstore_url not in _allowed_kvstore_urls():
        return None, ({"error": "Missing or disallowed X-Kvstore-Url header"}, 401)

    verify_req = urllib.request.Request(
        kvstore_url + "/auth/verify",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(verify_req, timeout=5) as resp:
            if resp.status != 200:
                return None, ({"error": "Invalid or expired token"}, 401)
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return None, ({"error": "Invalid or expired token"}, 401)
    except urllib.error.URLError as e:
        return None, ({"error": f"KVStore unreachable: {e}"}, 502)
    except Exception as e:
        return None, ({"error": f"KVStore verify failed: {e}"}, 502)

    username = (data or {}).get("username")
    if not username:
        return None, ({"error": "Invalid or expired token"}, 401)
    return username, None

@app.before_request
def _enabled_gate():
    # Runs before _require_auth below (Flask runs before_request hooks in
    # registration order), so a disabled app answers 503 without first
    # paying for a token-verify round trip to kvstore.
    if request.path == "/admin/settings":
        return None
    if get_setting(get_admin_settings_db(), "ENABLED", default="true") == "false":
        return jsonify({"error": "Service temporarily disabled by administrator"}), 503

@app.before_request
def _require_auth():
    path = request.path
    if path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PATH_PREFIXES):
        return None
    username, err = verify_token(request)
    if err:
        body, status = err
        return jsonify(body), status
    g.username = username
    return None

# -----------------------
# Admin settings
# -----------------------
# The global _require_auth before_request hook above already verifies the
# Bearer token (including the X-Kvstore-Url allowlist check) for every
# non-public path, /admin/settings included, and stashes the result on
# g.username. So the callable handed to register_admin_settings_routes just
# reuses that instead of re-verifying against kvstore a second time.
def _admin_verify_token():
    username = g.get("username")
    if not username:
        return None, ({"error": "Missing or invalid Authorization header"}, 401)
    return username, None

SETTINGS_SCHEMA = [
    SettingField(
        "ENABLED", "Enabled", "boolean", False, None,
        "When off, this app's functional endpoints return 503. /admin/settings "
        "stays reachable so you can turn it back on.",
    ),
    SettingField(
        "RSS_ALLOWED_KVSTORE_URLS", "Allowed KVStore URLs", "text", False, None,
        "Comma-separated kvstore instances allowed to issue tokens for this app "
        "(checked against the client's X-Kvstore-Url header on every request).",
    ),
]
SETTINGS_DEFAULTS = {
    "ENABLED": "true",
    "RSS_ALLOWED_KVSTORE_URLS": RSS_ALLOWED_KVSTORE_URLS_DEFAULT,
}

register_admin_settings_routes(
    app, SETTINGS_SCHEMA, get_admin_settings_db, _admin_verify_token, SETTINGS_DEFAULTS
)

# -----------------------
# Routes
# -----------------------
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/fetch_feed", methods=["GET"])
def fetch_feed():
    """Proxy endpoint for CList rss.js: fetch a single RSS/Atom feed and return items as JSON.
    Compatible with the opml2json /fetch_feed response format."""
    url = (request.args.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "url required"}), 400
    try:
        parsed = feedparser.parse(url)
        feed_title = (parsed.feed.get("title") or "").strip()
        items = []
        for entry in parsed.entries:
            item = {
                "guid":         entry.get("id") or entry.get("link") or "",
                "title":        entry.get("title"),
                "link":         entry.get("link"),
                "author":       (entry.get("author") or "").strip(),
                "published":    entry.get("published"),
                "summary":      entry.get("summary", ""),
                "source":       feed_title or url,
                "full_content": None,
            }
            if entry.get("content"):
                item["full_content"] = entry.content[0].get("value")
            elif entry.get("description"):
                item["full_content"] = entry.get("description")
            if entry.get("published_parsed"):
                item["published_ts"] = safe_struct_time_to_ts(entry.published_parsed)
            else:
                item["published_ts"] = now_ts()
            if entry.get("enclosures"):
                audio = [e["href"] for e in entry.enclosures
                         if (e.get("type") or "").startswith("audio/")]
                if audio:
                    item["audio"] = audio
            items.append(item)
        return jsonify({"ok": True, "title": feed_title, "feed_url": url, "items": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/collections")
def api_collections():
    """Public, unauthenticated: list available collections with feed counts."""
    out = []
    for m in _load_collection_manifests():
        db_path = _collection_db_path(m["slug"])
        feed_count = 0
        if os.path.exists(db_path):
            con = connect_db_at(db_path)
            try:
                row = con.execute("SELECT COUNT(*) AS c FROM feeds").fetchone()
                feed_count = int(row["c"] or 0)
            finally:
                con.close()
        out.append({"slug": m["slug"], "title": m["title"], "feed_count": feed_count})
    return jsonify(out)

@app.route("/api/collections/<slug>/items")
def api_collection_items(slug: str):
    """Public, unauthenticated: items for one collection. Same shape as
    /api/items but without bookmarked/read_at, since collections are
    anonymous/shared with no personal read-state concept."""
    if not re.match(r"^[A-Za-z0-9_-]+$", slug):
        return jsonify({"error": "invalid slug"}), 404
    db_path = _collection_db_path(slug)
    if not os.path.exists(db_path):
        return jsonify({"error": "collection not found"}), 404

    limit = int(request.args.get("limit", "200"))
    con = connect_db_at(db_path)
    try:
        cutoff = cutoff_ts()
        rows = con.execute("""
          SELECT e.id, e.title, e.link, e.author, e.published, e.content_html, e.thumbnail,
                 f.title AS feed_title, f.month_count, f.feed_author, f.feed_image
          FROM entries e
          JOIN feeds f ON f.id = e.feed_id
          WHERE e.published >= ?
        """, (cutoff,)).fetchall()
    finally:
        con.close()

    now = now_ts()
    items = []
    for r in rows:
        pub = int(r["published"] or now)
        mc = int(r["month_count"] or 0)
        items.append({
            "id": r["id"],
            "feed_title": r["feed_title"] or "(untitled feed)",
            "month_count": mc,
            "feed_author": r["feed_author"] or None,
            "feed_image": r["feed_image"] or None,
            "title": r["title"] or "(no title)",
            "link": r["link"],
            "author": r["author"] or "",
            "published": pub,
            "content_html": r["content_html"] or "",
            "thumbnail": r["thumbnail"] or None,
            "_score": post_score(pub, mc, now),
        })
    items.sort(key=lambda x: x["_score"], reverse=True)
    items = items[:limit]
    for item in items:
        del item["_score"]
    return jsonify(items)

@app.route("/api/items")
def api_items():
    limit = int(request.args.get("limit", "1600"))
    db = get_db()

    feed_id = request.args.get("feed_id")
    if feed_id:
        # Full history for one feed - ignores retention cutoff and read state,
        # since the point is to see everything stored, not the reading queue.
        rows = db.execute("""
          SELECT e.id, e.title, e.link, e.author, e.published, e.content_html, e.thumbnail, e.bookmarked, e.read_at,
                 f.title AS feed_title, f.month_count, f.feed_author, f.feed_image
          FROM entries e
          JOIN feeds f ON f.id = e.feed_id
          WHERE e.feed_id = ?
          ORDER BY e.published DESC
          LIMIT ?
        """, (int(feed_id), limit)).fetchall()
        return jsonify([{
            "id": r["id"],
            "feed_title": r["feed_title"] or "(untitled feed)",
            "month_count": int(r["month_count"] or 0),
            "feed_author": r["feed_author"] or None,
            "feed_image": r["feed_image"] or None,
            "title": r["title"] or "(no title)",
            "link": r["link"],
            "author": r["author"] or "",
            "published": int(r["published"] or now_ts()),
            "content_html": r["content_html"] or "",
            "thumbnail": r["thumbnail"] or None,
            "bookmarked": int(r["bookmarked"] or 0),
            "read_at": r["read_at"],
        } for r in rows])

    q = request.args.get("q", "").strip()
    if q:
        # Search across all stored posts regardless of feed, read state, or
        # retention cutoff - the point is to find something you remember, not
        # to browse the current reading queue.
        like = f"%{q}%"
        rows = db.execute("""
          SELECT e.id, e.title, e.link, e.author, e.published, e.content_html, e.thumbnail, e.bookmarked, e.read_at,
                 f.title AS feed_title, f.month_count, f.feed_author, f.feed_image
          FROM entries e
          JOIN feeds f ON f.id = e.feed_id
          WHERE e.title LIKE ? OR e.author LIKE ? OR e.content_html LIKE ?
          ORDER BY e.published DESC
          LIMIT ?
        """, (like, like, like, limit)).fetchall()
        return jsonify([{
            "id": r["id"],
            "feed_title": r["feed_title"] or "(untitled feed)",
            "month_count": int(r["month_count"] or 0),
            "feed_author": r["feed_author"] or None,
            "feed_image": r["feed_image"] or None,
            "title": r["title"] or "(no title)",
            "link": r["link"],
            "author": r["author"] or "",
            "published": int(r["published"] or now_ts()),
            "content_html": r["content_html"] or "",
            "thumbnail": r["thumbnail"] or None,
            "bookmarked": int(r["bookmarked"] or 0),
            "read_at": r["read_at"],
        } for r in rows])

    filter_mode = request.args.get("filter", "unread").lower()
    cutoff = cutoff_ts()

    # Build WHERE clause based on filter mode
    if filter_mode == "read":
        where_clause = "e.read_at IS NOT NULL AND e.published >= ?"
        params = (cutoff, limit)
    elif filter_mode == "bookmarked":
        where_clause = "e.bookmarked = 1"
        params = (limit,)
    elif filter_mode == "all":
        where_clause = "e.published >= ?"
        params = (cutoff, limit)
    else:  # unread (default)
        where_clause = "e.read_at IS NULL AND e.published >= ?"
        params = (cutoff, limit)

    query = f"""
      SELECT e.id, e.title, e.link, e.author, e.published, e.content_html, e.thumbnail, e.bookmarked, e.read_at,
             f.title AS feed_title, f.month_count, f.feed_author, f.feed_image
      FROM entries e
      JOIN feeds f ON f.id = e.feed_id
      WHERE {where_clause}
    """

    # Strip the LIMIT placeholder from params — we apply the limit after
    # Python-side scoring so the cut happens on the ranked list, not before.
    sql_params = params[:-1]
    rows = db.execute(query, sql_params).fetchall()

    now = now_ts()
    items = []
    for r in rows:
        pub = int(r["published"] or now)
        mc  = int(r["month_count"] or 0)
        items.append({
            "id": r["id"],
            "feed_title": r["feed_title"] or "(untitled feed)",
            "month_count": mc,
            "feed_author": r["feed_author"] or None,
            "feed_image": r["feed_image"] or None,
            "title": r["title"] or "(no title)",
            "link": r["link"],
            "author": r["author"] or "",
            "published": pub,
            "content_html": r["content_html"] or "",
            "thumbnail": r["thumbnail"] or None,
            "bookmarked": int(r["bookmarked"] or 0),
            "read_at": r["read_at"],
            "_score": post_score(pub, mc, now),
        })

    items.sort(key=lambda x: x["_score"], reverse=True)
    items = items[:limit]

    # Remove internal scoring field before sending to client
    for item in items:
        del item["_score"]

    return jsonify(items)

@app.route("/api/mark_read", methods=["POST"])
def api_mark_read():
    entry_id = int(request.json["id"])
    with DB_WRITE_LOCK:
        db = get_db()
        db.execute("UPDATE entries SET read_at=? WHERE id=?", (now_ts(), entry_id))
        db.commit()
    return jsonify({"ok": True})

@app.route("/api/mark_all_read", methods=["POST"])
def api_mark_all_read():
    cutoff = cutoff_ts()
    with DB_WRITE_LOCK:
        db = get_db()
        db.execute(
            "UPDATE entries SET read_at=? WHERE read_at IS NULL AND published >= ?",
            (now_ts(), cutoff)
        )
        db.commit()
    return jsonify({"ok": True})

@app.route("/api/toggle_bookmark", methods=["POST"])
def api_toggle_bookmark():
    entry_id = int(request.json["id"])
    with DB_WRITE_LOCK:
        db = get_db()
        row = db.execute("SELECT bookmarked FROM entries WHERE id=?", (entry_id,)).fetchone()
        cur = int(row["bookmarked"] or 0)
        new = 0 if cur else 1
        db.execute("UPDATE entries SET bookmarked=? WHERE id=?", (new, entry_id))
        db.commit()
    return jsonify({"ok": True, "bookmarked": new})


@app.route("/api/config")
def api_config():
    return jsonify({
        "db_path": ACTIVE_DB_PATH,
        "configured_db_path": DB_PATH_ABS,
        "db_exists": os.path.exists(ACTIVE_DB_PATH),
        "configured_db_exists": os.path.exists(DB_PATH_ABS),
        "port": PORT,
        "retention_days": RETENTION_DAYS,
        "user_agent": USER_AGENT,
    })

@app.route("/api/db_list")
def api_db_list():
    dbs = _scan_databases()
    cur = os.path.basename(ACTIVE_DB_PATH)
    # Ensure current appears in list if it exists but isn't a *.db in directory (e.g., fallback)
    if cur and cur.lower().endswith(".db") and cur not in dbs and os.path.exists(ACTIVE_DB_PATH):
        dbs = [cur] + dbs
    return jsonify({"ok": True, "db_dir": DB_DIR, "current": cur, "dbs": dbs})

@app.route("/api/db_select", methods=["POST"])
def api_db_select():
    data = request.get_json(silent=True) or {}
    name = (data.get("db") or data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "db required"}), 400

    dbs = _scan_databases()
    if name not in dbs:
        return jsonify({"ok": False, "error": f"Unknown db: {name}"}), 404

    # Do not switch while an update job is running
    job = get_job(_active_job_id) if _active_job_id else None
    if job and job.get("state") in ("running", "starting"):
        return jsonify({"ok": False, "error": "Cannot switch databases while an update is running."}), 409

    with DB_WRITE_LOCK:
        _set_current_db_abs(os.path.join(DB_DIR, name))
        init_db()

    return jsonify({"ok": True, "current": os.path.basename(ACTIVE_DB_PATH), "db_path": ACTIVE_DB_PATH})


def _require_no_running_update():
    if _any_update_job_running():
        return jsonify({"ok": False, "error": "Cannot modify feeds while an update is running."}), 409
    return None


@app.route("/api/feeds")
def api_feeds():
    q = (request.args.get("q") or "").strip()
    limit = int(request.args.get("limit") or "200")
    limit = max(1, min(limit, 1000))

    db = get_db()
    if q:
        like = f"%{q}%"
        rows = db.execute(
            "SELECT id, url, title FROM feeds WHERE url LIKE ? OR title LIKE ? ORDER BY COALESCE(title, url) LIMIT ?",
            (like, like, limit),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, url, title FROM feeds ORDER BY COALESCE(title, url) LIMIT ?",
            (limit,),
        ).fetchall()

    return jsonify({"ok": True, "feeds": [{"id": r["id"], "url": r["url"], "title": r["title"]} for r in rows]})


@app.route("/api/feed/<int:feed_id>")
def api_feed_get(feed_id: int):
    db = get_db()
    r = db.execute("SELECT id, url, title, fail_count, error_msg, feed_author, feed_image FROM feeds WHERE id=?", (feed_id,)).fetchone()
    if not r:
        return jsonify({"ok": False, "error": "Unknown feed"}), 404
    return jsonify({"ok": True, "feed": {
        "id": r["id"], "url": r["url"], "title": r["title"],
        "fail_count": int(r["fail_count"] or 0), "error_msg": r["error_msg"],
        "author": r["feed_author"], "image": r["feed_image"],
    }})


def _update_one_feed_now(feed_id: int):
    # Caller should already hold DB_WRITE_LOCK.
    try:
        asyncio.run(update_feeds_async(feed_ids=[feed_id], only_due=False))
    except RuntimeError:
        # If an event loop is already running in this thread (unlikely in Flask), skip.
        pass


@app.route("/api/feed_discover", methods=["POST"])
def api_feed_discover():
    """Discover the RSS/Atom URL for a given website URL without creating a feed."""
    data = request.get_json(silent=True) or {}
    input_url = (data.get("url") or "").strip()
    if not input_url:
        return jsonify({"ok": False, "error": "url required"}), 400
    try:
        feed_url, kind = discover_feed_url(input_url)
        title = None
        try:
            feed_bytes, ct = _fetch_url_bytes(feed_url)
            parsed = feedparser.parse(feed_bytes)
            title = (parsed.feed.get("title") or "").strip() or None
        except Exception:
            pass
        return jsonify({"ok": True, "feed_url": feed_url, "kind": kind, "title": title})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/feed_create", methods=["POST"])
def api_feed_create():
    block = _require_no_running_update()
    if block:
        return block

    data = request.get_json(silent=True) or {}
    input_url = (data.get("url") or "").strip()
    if not input_url:
        return jsonify({"ok": False, "error": "url required"}), 400

    try:
        feed_url, kind = discover_feed_url(input_url)
        feed_bytes, ct = _fetch_url_bytes(feed_url)
        if not _looks_like_feed(ct, feed_bytes):
            return jsonify({"ok": False, "error": "The discovered URL did not look like an RSS/Atom feed."}), 400
        parsed = feedparser.parse(feed_bytes)
        title = (parsed.feed.get("title") or "").strip() or None
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    with DB_WRITE_LOCK:
        db = connect_db()
        try:
            existing = db.execute("SELECT id, url, title FROM feeds WHERE url=?", (feed_url,)).fetchone()
            if existing:
                feed_id = existing["id"]
                # Update title if we learned it
                if title and not existing["title"]:
                    db.execute("UPDATE feeds SET title=? WHERE id=?", (title, feed_id))
                    db.commit()
                out_title = title or existing["title"]
                out = {"id": feed_id, "url": existing["url"], "title": out_title}
                return jsonify({"ok": True, "kind": kind, "feed": out, "existing": True})

            cur = db.execute("INSERT INTO feeds(url,title,next_fetch) VALUES(?,?,?)", (feed_url, title, 0))
            feed_id = cur.lastrowid
            db.commit()

            # Fetch immediately so the right pane can refresh with new entries.
            _update_one_feed_now(feed_id)
            out = {"id": feed_id, "url": feed_url, "title": title}
            return jsonify({"ok": True, "kind": kind, "feed": out, "existing": False})
        finally:
            db.close()


@app.route("/api/feed_update", methods=["POST"])
def api_feed_update():
    block = _require_no_running_update()
    if block:
        return block

    data = request.get_json(silent=True) or {}
    feed_id = int(data.get("id") or 0)
    url = (data.get("url") or "").strip()
    title = (data.get("title") or "").strip() or None
    # Manually cleared to blank means "let the harvester fill this back in",
    # so store NULL rather than "" - COALESCE(feed_author, ...) only fills a
    # NULL, never a value someone deliberately typed and saved as empty vs blank.
    author = (data.get("author") or "").strip() or None
    image = (data.get("image") or "").strip() or None
    if not feed_id:
        return jsonify({"ok": False, "error": "id required"}), 400
    if not url:
        return jsonify({"ok": False, "error": "url required"}), 400
    if not re.match(r"^https?://", url, re.I):
        return jsonify({"ok": False, "error": "URL must start with http:// or https://"}), 400

    with DB_WRITE_LOCK:
        db = connect_db()
        try:
            row = db.execute("SELECT id, url, title FROM feeds WHERE id=?", (feed_id,)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Unknown feed"}), 404

            try:
                if url != row["url"]:
                    db.execute(
                        "UPDATE feeds SET url=?, title=?, feed_author=?, feed_image=?, etag=NULL, last_modified=NULL, fail_count=0, next_fetch=0 WHERE id=?",
                        (url, title, author, image, feed_id),
                    )
                else:
                    db.execute(
                        "UPDATE feeds SET title=?, feed_author=?, feed_image=? WHERE id=?",
                        (title, author, image, feed_id),
                    )
                db.commit()
            except sqlite3.IntegrityError:
                return jsonify({"ok": False, "error": "A feed with that URL already exists."}), 409

            # Refresh entries after update.
            _update_one_feed_now(feed_id)
            out = {"id": feed_id, "url": url, "title": title, "author": author, "image": image}
            return jsonify({"ok": True, "feed": out})
        finally:
            db.close()


@app.route("/api/feed_delete", methods=["POST"])
def api_feed_delete():
    block = _require_no_running_update()
    if block:
        return block

    data = request.get_json(silent=True) or {}
    feed_id = int(data.get("id") or 0)
    if not feed_id:
        return jsonify({"ok": False, "error": "id required"}), 400

    with DB_WRITE_LOCK:
        db = connect_db()
        try:
            row = db.execute("SELECT id FROM feeds WHERE id=?", (feed_id,)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Unknown feed"}), 404
            db.execute("DELETE FROM entries WHERE feed_id=?", (feed_id,))
            db.execute("DELETE FROM feeds WHERE id=?", (feed_id,))
            db.commit()
        finally:
            db.close()

    return jsonify({"ok": True})

@app.route("/api/feeds_errors")
def api_feeds_errors():
    db = get_db()
    rows = db.execute(
        "SELECT id, url, title, fail_count, error_msg, last_fetch, last_ok FROM feeds"
        " WHERE fail_count > 0 ORDER BY fail_count DESC, COALESCE(title, url)"
    ).fetchall()
    return jsonify({"ok": True, "feeds": [{
        "id": r["id"], "url": r["url"], "title": r["title"],
        "fail_count": int(r["fail_count"] or 0), "error_msg": r["error_msg"],
        "last_fetch": r["last_fetch"], "last_ok": r["last_ok"],
    } for r in rows]})


@app.route("/api/feed_retry", methods=["POST"])
def api_feed_retry():
    block = _require_no_running_update()
    if block:
        return block

    data = request.get_json(silent=True) or {}
    feed_id = int(data.get("id") or 0)
    if not feed_id:
        return jsonify({"ok": False, "error": "id required"}), 400

    with DB_WRITE_LOCK:
        db = connect_db()
        try:
            row = db.execute("SELECT id FROM feeds WHERE id=?", (feed_id,)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Unknown feed"}), 404
            db.execute(
                "UPDATE feeds SET fail_count=0, next_fetch=0, error_msg=NULL WHERE id=?",
                (feed_id,)
            )
            db.commit()
            _update_one_feed_now(feed_id)

            r = db.execute(
                "SELECT id, url, title, fail_count, error_msg, last_ok FROM feeds WHERE id=?",
                (feed_id,)
            ).fetchone()
        finally:
            db.close()

    return jsonify({"ok": True, "feed": {
        "id": r["id"], "url": r["url"], "title": r["title"],
        "fail_count": int(r["fail_count"] or 0), "error_msg": r["error_msg"],
        "last_ok": r["last_ok"],
    }})


@app.route("/api/stats")
def api_stats():
    db = get_db()
    feeds = db.execute("SELECT COUNT(*) AS c FROM feeds").fetchone()["c"]
    unread = db.execute("SELECT COUNT(*) AS c FROM entries WHERE read_at IS NULL AND published >= ?", (cutoff_ts(),)).fetchone()["c"]
    bookmarked = db.execute("SELECT COUNT(*) AS c FROM entries WHERE bookmarked = 1").fetchone()["c"]
    return jsonify({
        "feeds": feeds,
        "unread": unread,
        "bookmarked": bookmarked,
        "retention_days": RETENTION_DAYS,
        "scheduler_enabled": _scheduler_enabled,
    })

@app.route("/api/update_start", methods=["POST"])
def api_update_start():
    job_id = start_update_job(full_sweep=True)
    return jsonify({"ok": True, "job_id": job_id})

@app.route("/api/update_progress")
def api_update_progress():
    job_id = request.args.get("job_id")
    if not job_id:
        return jsonify({"ok": False, "error": "job_id required"}), 400
    job = get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "unknown job_id"}), 404
    return jsonify({"ok": True, "job": job})

@app.route("/api/update_cancel", methods=["POST"])
def api_update_cancel():
    job_id = (request.json or {}).get("job_id")
    if not job_id:
        return jsonify({"ok": False, "error": "job_id required"}), 400
    ok = cancel_update_job(job_id)
    return jsonify({"ok": ok})

@app.route("/api/scheduler", methods=["POST"])
def api_scheduler():
    global _scheduler_enabled
    enabled = bool((request.json or {}).get("enabled"))
    _scheduler_enabled = enabled
    return jsonify({"ok": True, "scheduler_enabled": _scheduler_enabled})


@app.route("/api/opml_export")
def api_opml_export():
    db = get_db()
    feeds = db.execute("SELECT url, title FROM feeds ORDER BY COALESCE(title, url)").fetchall()
    data = _build_opml([{"url": r["url"], "title": r["title"]} for r in feeds])
    return Response(
        data,
        mimetype="text/xml",
        headers={"Content-Disposition": "attachment; filename=feeds.opml"},
    )

@app.route("/api/opml_import", methods=["POST"])
def api_opml_import():
    f = request.files.get("opml")
    if not f:
        return jsonify({"ok": False, "error": "Missing file field 'opml'."}), 400

    mode = (request.form.get("mode") or "merge").strip().lower()
    new_db_name = (request.form.get("new_db_name") or "").strip()

    try:
        pairs = _parse_opml(f.read())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    if mode not in ("merge", "replace", "newdb"):
        return jsonify({"ok": False, "error": f"Unknown mode: {mode}"}), 400

    imported = 0
    skipped = 0

    # Important: serialize DB writes
    with DB_WRITE_LOCK:
        global DB_PATH, DB_PATH_ABS, ACTIVE_DB_PATH

        if mode == "newdb":
            base_dir = DB_DIR
            safe_name = _sanitize_db_name(new_db_name)
            if not safe_name:
                safe_name = "rss_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".db"
            new_path = os.path.abspath(os.path.join(base_dir, safe_name))
            parent = os.path.dirname(new_path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            if os.path.exists(new_path):
                return jsonify({"ok": False, "error": f"DB already exists: {new_path}"}), 400

            # Switch the app to this new DB
            _set_current_db_abs(new_path)

            # Create schema
            init_db()

            con = connect_db()
            try:
                con.execute("BEGIN")
                for url, title in pairs:
                    cur = con.execute(
                        "INSERT OR IGNORE INTO feeds(url, title) VALUES(?, ?)",
                        (url, title),
                    )
                    if cur.rowcount == 1:
                        imported += 1
                    else:
                        skipped += 1
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            finally:
                con.close()

            return jsonify({"ok": True, "mode": mode, "imported": imported, "skipped": skipped, "db_path": ACTIVE_DB_PATH})

        # merge/replace operate on current DB
        con = connect_db()
        try:
            con.execute("BEGIN")

            if mode == "replace":
                # Replace feed list: clear feeds + entries
                con.execute("DELETE FROM entries")
                con.execute("DELETE FROM feeds")

            for url, title in pairs:
                cur = con.execute(
                    "INSERT OR IGNORE INTO feeds(url, title) VALUES(?, ?)",
                    (url, title),
                )
                # rowcount is 1 for insert, 0 for ignored
                if cur.rowcount == 1:
                    imported += 1
                else:
                    skipped += 1

            con.execute("COMMIT")
        except Exception as e:
            con.execute("ROLLBACK")
            return jsonify({"ok": False, "error": str(e)}), 500
        finally:
            con.close()

    return jsonify({"ok": True, "mode": mode, "imported": imported, "skipped": skipped, "db_path": ACTIVE_DB_PATH})

# Run schema creation + migrations, collections setup, and the background
# scheduler at import time (covers gunicorn and direct invocation). This is
# the real production startup path: under gunicorn, `if __name__ == "__main__"`
# below never executes, since gunicorn imports this module rather than
# running it as a script.
try:
    init_db()
except Exception as _e:
    print(f"[WARN] init_db failed at startup: {_e}", file=sys.stderr)

try:
    with COLLECTIONS_WRITE_LOCK:
        ensure_collections()
except Exception as _e:
    print(f"[WARN] ensure_collections failed at startup: {_e}", file=sys.stderr)

start_background_scheduler()


def import_feeds_txt(path: str = "feeds.txt"):
    if not os.path.exists(path):
        return 0
    con = connect_db()
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        con.execute("BEGIN")
        try:
            for line in f:
                u = line.strip()
                if not u or u.startswith("#"):
                    continue
                ensure_feed(con, u)
                n += 1
            con.commit()
        except Exception:
            con.rollback()
            raise
    con.close()
    return n

def _is_server_running(host: str, port: int, timeout: float = 0.25) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def acquire_single_instance_lock(lockfile: str = ".localrss.lock") -> object | None:
    """
    Cross-platform best-effort single-instance lock.
    - Windows: msvcrt.locking
    - POSIX: fcntl.flock
    Returns an open file handle if lock acquired, else None.
    Keep the returned handle alive for the lifetime of the process.
    """
    try:
        f = open(lockfile, "a+b")
    except Exception:
        return None

    try:
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                return f
            except OSError:
                try:
                    f.close()
                except Exception:
                    pass
                return None
        else:
            import fcntl
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return f
            except OSError:
                try:
                    f.close()
                except Exception:
                    pass
                return None
    except Exception:
        try:
            f.close()
        except Exception:
            pass
        return None



def import_default_opml_if_needed(path: str = "feeds.opml") -> int:
    """If the feeds table is empty and an OPML file exists, import it (no duplicates)."""
    if not os.path.exists(path):
        return 0
    con = connect_db()
    try:
        cur = con.execute("SELECT COUNT(*) FROM feeds")
        count = int(cur.fetchone()[0] or 0)
        if count > 0:
            return 0
        xml_bytes = open(path, "rb").read()
        pairs = _parse_opml(xml_bytes)  # list of (url, title)
        n = 0
        con.execute("BEGIN")
        try:
            for url, title in pairs:
                if not url:
                    continue
                con.execute(
                    "INSERT OR IGNORE INTO feeds(url, title, next_fetch) VALUES(?, ?, 0)",
                    (url, title or None),
                )
                n += 1
            con.commit()
        except Exception:
            con.rollback()
            raise
        return n
    finally:
        con.close()


if __name__ == "__main__":
    init_db()

    print(f"[INFO] LocalRSSReader v{APP_VERSION} starting…")
    print(f"[INFO] Using database: {ACTIVE_DB_PATH}")

    try:
        imported = import_default_opml_if_needed("feeds.opml")
        if imported:
            print(f"[INFO] Imported {imported} feeds from feeds.opml (empty DB).")
    except Exception as e:
        print(f"[WARN] Could not import default feeds.opml: {e}", file=sys.stderr)

    # Prevent accidental double-launch (common when double-clicking the .bat twice)
    lock_handle = acquire_single_instance_lock(".localrss.lock")
    if lock_handle is None:
        # Another instance likely running; just exit quietly.
        # (The .bat file will open the browser.)
        raise SystemExit(0)

    # If port already has a server, exit (avoids a second python process)
    if _is_server_running("127.0.0.1", PORT):
        raise SystemExit(0)

    # start_background_scheduler() already ran at module import time above.
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)