# LocalRSSReader — Pre-Alpha

This is a **pre-alpha** Windows-first local RSS/Atom reader.

Pre-alpha means:
- features and data formats may change
- rough edges are expected
- please report crashes, data-loss risks, and confusing workflows

## Quick start (first run)

1. Download the ZIP and extract it to a folder you control (e.g., `Documents`).
2. Open the extracted folder.
3. Double-click **`run_localrss.bat`**.

On the **first run**, the script will:
- create a Python virtual environment (venv)
- install dependencies from `requirements.txt`
- start the local server
- open your browser to the app

## Subsequent runs

Just double-click **`run_localrss.bat`** again.
It will reuse the existing environment and database settings.

## Databases and safety

- The app uses a local **SQLite** database (`.db`).
- By default, it will use the most recently used database in your database directory.
- Switching databases is supported from the sidebar.

**Safety note:** Some actions are destructive:
- **Replace feeds** during OPML import will remove existing feeds (and their entries).
- **Delete feed** removes that feed and its stored entries.

If your data matters, **back up your `.db` file** before doing destructive operations.

## Included OPML

This package includes `feeds.opml` as an example feed list you can import from the sidebar:
- Import OPML → Add / Replace / New database

## Feedback / bug reports

When reporting an issue, please include:
- what you were trying to do
- what you expected
- what happened instead
- the console output from the server window (copy/paste)
- which database file you were using (shown in the UI top bar)

Thanks!
