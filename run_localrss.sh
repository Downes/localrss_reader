#!/usr/bin/env bash
set -e

echo "Starting LocalRSSReader (pre-alpha)"

if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing/updating dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Default DB location (can be overridden)
if [ -z "$RSS_DB" ]; then
  export RSS_DB="$HOME/localrss/rss.db"
fi

echo "Using RSS_DB=$RSS_DB"
python app.py
