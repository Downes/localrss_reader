#!/usr/bin/env python3
"""
LocalRSS Reader - System Tray Application
Runs Flask server in background with database sync capabilities
"""
import os
import sys
import threading
import webbrowser
import subprocess
import time
from pathlib import Path
import json

# GUI imports
try:
    import pystray
    from pystray import MenuItem as item
    from PIL import Image, ImageDraw
except ImportError:
    print("Installing required packages...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pystray", "Pillow"])
    import pystray
    from pystray import MenuItem as item
    from PIL import Image, ImageDraw

# Get the directory where this script is located
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    BASE_DIR = Path(sys._MEIPASS)
    CONFIG_DIR = Path(os.path.expanduser("~/.localrss"))
else:
    # Running as script
    BASE_DIR = Path(__file__).parent
    CONFIG_DIR = BASE_DIR

# Ensure config directory exists
CONFIG_DIR.mkdir(exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config.json"

# Default configuration
DEFAULT_CONFIG = {
    "vps_host": "158.69.209.43",
    "vps_user": "ubuntu",
    "vps_db_path": "/srv/apps/localrss_reader/data/rss.db",
    "local_db_path": str(CONFIG_DIR / "rss.db"),
    "port": 8787,
    "auto_sync_on_start": True
}


def load_config():
    """Load configuration from file or create default"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            # Merge with defaults for any missing keys
            return {**DEFAULT_CONFIG, **config}
    else:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()


def save_config(config):
    """Save configuration to file"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


class LocalRSSApp:
    def __init__(self):
        self.config = load_config()
        self.flask_thread = None
        self.flask_app = None
        self.running = False
        self.port = self.config['port']

        # Ensure data directory exists
        db_path = Path(self.config['local_db_path'])
        db_path.parent.mkdir(parents=True, exist_ok=True)

    def create_icon(self):
        """Create a simple RSS icon"""
        # Create a 64x64 image with RSS symbol
        img = Image.new('RGB', (64, 64), color='white')
        draw = ImageDraw.Draw(img)

        # Draw RSS symbol (simplified)
        draw.ellipse([8, 40, 16, 48], fill='orange')
        draw.pieslice([4, 20, 32, 48], 0, 90, fill='orange')
        draw.pieslice([4, 4, 48, 48], 0, 90, fill='orange')

        return img

    def start_flask(self):
        """Start Flask server in background thread"""
        if self.running:
            return

        def run_flask():
            # Set environment variables
            os.environ['RSS_DB'] = self.config['local_db_path']
            os.environ['RSS_PORT'] = str(self.port)

            # Import and run Flask app
            sys.path.insert(0, str(BASE_DIR))

            try:
                from app import app as flask_app
                self.flask_app = flask_app
                flask_app.run(host='127.0.0.1', port=self.port, debug=False, use_reloader=False)
            except Exception as e:
                print(f"Flask error: {e}")

        self.flask_thread = threading.Thread(target=run_flask, daemon=True)
        self.flask_thread.start()
        self.running = True

        # Wait a moment for Flask to start
        time.sleep(2)

    def open_browser(self, icon=None, item=None):
        """Open the RSS reader in default browser"""
        if not self.running:
            self.start_flask()
        webbrowser.open(f'http://127.0.0.1:{self.port}')

    def sync_from_vps(self, icon=None, item=None):
        """Download database from VPS"""
        try:
            if icon:
                icon.notify("Syncing from VPS...", "LocalRSS Reader")

            cmd = [
                'scp',
                f"{self.config['vps_user']}@{self.config['vps_host']}:{self.config['vps_db_path']}",
                self.config['local_db_path']
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                if icon:
                    icon.notify("Sync complete!", "Database downloaded from VPS")
            else:
                if icon:
                    icon.notify("Sync failed!", f"Error: {result.stderr[:100]}")
        except subprocess.TimeoutExpired:
            if icon:
                icon.notify("Sync timeout!", "Connection to VPS timed out")
        except Exception as e:
            if icon:
                icon.notify("Sync error!", str(e)[:100])

    def sync_to_vps(self, icon=None, item=None):
        """Upload database to VPS"""
        try:
            if icon:
                icon.notify("Uploading to VPS...", "LocalRSS Reader")

            cmd = [
                'scp',
                self.config['local_db_path'],
                f"{self.config['vps_user']}@{self.config['vps_host']}:{self.config['vps_db_path']}"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                # Restart the Docker container on VPS
                restart_cmd = [
                    'ssh',
                    f"{self.config['vps_user']}@{self.config['vps_host']}",
                    'cd /srv/apps/localrss_reader && docker compose restart'
                ]
                subprocess.run(restart_cmd, capture_output=True, timeout=30)

                if icon:
                    icon.notify("Upload complete!", "Database uploaded to VPS")
            else:
                if icon:
                    icon.notify("Upload failed!", f"Error: {result.stderr[:100]}")
        except subprocess.TimeoutExpired:
            if icon:
                icon.notify("Upload timeout!", "Connection to VPS timed out")
        except Exception as e:
            if icon:
                icon.notify("Upload error!", str(e)[:100])

    def quit_app(self, icon=None, item=None):
        """Quit the application"""
        if icon:
            icon.stop()
        sys.exit(0)

    def run(self):
        """Run the system tray application"""
        # Auto-sync on start if configured
        if self.config['auto_sync_on_start']:
            print("Auto-syncing database from VPS...")
            self.sync_from_vps()

        # Start Flask server
        self.start_flask()

        # Create system tray icon
        icon = pystray.Icon(
            "localrss",
            self.create_icon(),
            "LocalRSS Reader",
            menu=pystray.Menu(
                item('Open RSS Reader', self.open_browser, default=True),
                item('Sync from VPS', self.sync_from_vps),
                item('Upload to VPS', self.sync_to_vps),
                pystray.Menu.SEPARATOR,
                item('Quit', self.quit_app)
            )
        )

        # Auto-open browser on start
        time.sleep(1)
        self.open_browser()

        # Run the icon (this blocks)
        icon.run()


if __name__ == '__main__':
    print("Starting LocalRSS Reader...")
    print(f"Configuration directory: {CONFIG_DIR}")

    app = LocalRSSApp()
    app.run()
