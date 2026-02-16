# LocalRSS Reader - Desktop Application

A standalone Windows desktop application with system tray integration and automatic database syncing with your VPS.

## Features

- 🖥️ **Standalone Application**: No Python installation required for end users
- 🔄 **Auto Sync**: Automatically syncs database from VPS on startup
- 📊 **System Tray**: Runs in background with easy access from system tray
- 🌐 **Browser-based UI**: Opens in your default browser for familiar experience
- 🔒 **SSH Sync**: Secure database synchronization using SSH/SCP

## For Users (Running the App)

### Prerequisites
- Windows 10 or later
- SSH access configured to your VPS (SSH key must be set up)

### First Time Setup

1. Extract the `LocalRSS` folder to your desired location (e.g., `C:\Program Files\LocalRSS\`)

2. Set up SSH key authentication to your VPS:
   ```bash
   # On Windows, use Git Bash or PowerShell
   ssh-copy-id ubuntu@158.69.209.43
   ```
   Or manually copy your SSH key to the VPS.

3. Run `LocalRSS.exe`

4. The app will:
   - Create configuration in `%USERPROFILE%\.localrss\`
   - Download the database from VPS
   - Start the local server
   - Open your browser to the RSS reader

### Using the App

**System Tray Icon**
- Double-click: Open RSS Reader in browser
- Right-click menu:
  - **Open RSS Reader**: Launch in browser
  - **Sync from VPS**: Download latest database
  - **Upload to VPS**: Upload local changes to VPS
  - **Quit**: Exit the application

**Database Syncing**
- **Auto-sync on start**: Database automatically downloads from VPS when you start the app
- **Manual sync**: Use the tray menu to sync whenever needed
- **Upload changes**: After making changes locally, use "Upload to VPS" to sync back

### Configuration

Configuration is stored in `%USERPROFILE%\.localrss\config.json`:

```json
{
  "vps_host": "158.69.209.43",
  "vps_user": "ubuntu",
  "vps_db_path": "/srv/apps/localrss_reader/data/rss.db",
  "local_db_path": "C:\\Users\\YourName\\.localrss\\rss.db",
  "port": 8787,
  "auto_sync_on_start": true
}
```

Edit this file to customize settings.

## For Developers (Building the App)

### Prerequisites for Building
- Python 3.8 or higher
- Git (optional, for cloning)

### Building from Source

1. Clone or download the repository

2. Install dependencies:
   ```bash
   pip install -r requirements-desktop.txt
   ```

3. Build the executable:
   ```bash
   # On Windows
   build_desktop.bat

   # On Linux/Mac (for testing)
   pyinstaller localrss.spec --clean
   ```

4. The executable will be in `dist\LocalRSS\`

### Project Structure

```
localrss_reader/
├── tray_app.py              # System tray application (entry point)
├── app.py                   # Flask application
├── static/                  # Web UI files
│   └── index.html
├── localrss.spec           # PyInstaller build configuration
├── requirements.txt         # Server requirements
├── requirements-desktop.txt # Desktop app requirements
├── build_desktop.bat       # Windows build script
└── README_DESKTOP.md       # This file
```

### How It Works

1. **tray_app.py**: Main entry point that creates a system tray icon
2. **Flask Server**: Runs in a background thread on localhost:8787
3. **Database Sync**: Uses SSH/SCP to sync database with VPS
4. **PyInstaller**: Bundles everything into a standalone executable

## Troubleshooting

### "SSH connection failed"
- Ensure SSH key authentication is set up
- Test manually: `ssh ubuntu@158.69.209.43`

### "Port already in use"
- Another instance may be running (check system tray)
- Change port in config.json

### "Database sync timeout"
- Check your internet connection
- Verify VPS is accessible: `ping 158.69.209.43`

### App doesn't start
- Run from command line to see error messages:
  ```bash
  dist\LocalRSS\LocalRSS.exe
  ```

## Advanced Usage

### Running Multiple Instances
Change the port in config.json to run multiple instances.

### Custom Database Location
Edit `local_db_path` in config.json to use a different location.

### Disable Auto-sync
Set `"auto_sync_on_start": false` in config.json.

## Security Notes

- Database syncing uses SSH/SCP (secure)
- Local server only listens on 127.0.0.1 (not accessible from network)
- Configuration and database stored in user profile directory

## License

Same as the main LocalRSS Reader project.
