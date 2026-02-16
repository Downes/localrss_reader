# Running LocalRSSReader on macOS / Linux

LocalRSSReader is written in Python (Flask + SQLite) and runs on macOS and Linux
with no code changes. The only platform-specific part is the launcher script.

## Quick start

1. Unzip the archive
2. Open a terminal in the project directory
3. Make the launcher executable:

   chmod +x run_localrss.sh

4. Run it:

   ./run_localrss.sh

The script will:
- create a Python virtual environment if needed
- install dependencies
- create the database directory if needed
- start the server

## Database location

By default, the database will be created at:

    ~/localrss/rss.db

You can override this by setting the RSS_DB environment variable:

    RSS_DB=/path/to/rss.db ./run_localrss.sh

## Notes

- This is a **pre-alpha** release
- The app is intended for **single-user, local use**
- Back up your `.db` file if the data matters to you
