# Legacy VPS synchronization tray tool

Archived instructions for tray_app.py, not the new standalone downloads.

# Quick Start Guide - Windows Desktop App

## Step 1: Set Up SSH Key (One-time setup)

Before using the desktop app, you need SSH key authentication to your VPS:

### Option A: Using Git Bash (Recommended)
1. Install [Git for Windows](https://git-scm.com/download/win) if you haven't already
2. Open Git Bash
3. Run:
   ```bash
   ssh-keygen -t ed25519
   ssh-copy-id ubuntu@158.69.209.43
   ```

### Option B: Using PowerShell
1. Generate SSH key:
   ```powershell
   ssh-keygen -t ed25519
   ```
2. Copy the public key to VPS:
   ```powershell
   type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh ubuntu@158.69.209.43 "cat >> ~/.ssh/authorized_keys"
   ```

3. Test the connection:
   ```bash
   ssh ubuntu@158.69.209.43
   ```
   If you can connect without a password, you're ready!

## Step 2: Build the Desktop App

### Prerequisites
- Python 3.8+ ([Download here](https://www.python.org/downloads/))
- Git (optional, for cloning the repo)

### Build Steps
1. Open Command Prompt or PowerShell in the localrss_reader directory
2. Run:
   ```bash
   build_desktop.bat
   ```
3. Wait for the build to complete (2-5 minutes)
4. Find your app in: `dist\LocalRSS\LocalRSS.exe`

## Step 3: Run the App

1. Navigate to `dist\LocalRSS\`
2. Double-click `LocalRSS.exe`
3. The app will:
   - Download the database from your VPS
   - Start in your system tray (look for RSS icon)
   - Open your browser automatically

## Using the App

### System Tray Menu
Right-click the RSS icon in your system tray:
- **Open RSS Reader** - Opens in your browser
- **Sync from VPS** - Download latest data
- **Upload to VPS** - Upload your changes
- **Quit** - Exit the app

### Tips
- Double-click the tray icon to quickly open the reader
- The app auto-syncs from VPS on startup
- Your data is stored in: `%USERPROFILE%\.localrss\`
- After making changes locally, remember to "Upload to VPS" to sync

## Troubleshooting

**"SSH connection failed"**
- Make sure you completed Step 1 (SSH key setup)
- Test: `ssh ubuntu@158.69.209.43` should work without password

**"Build failed"**
- Make sure Python is in your PATH
- Try: `python --version` (should show 3.8 or higher)
- Reinstall dependencies: `pip install -r requirements-desktop.txt`

**Port 8787 already in use**
- Check if LocalRSS is already running (check system tray)
- Or edit `%USERPROFILE%\.localrss\config.json` to use a different port

## Next Steps

- Read [README_DESKTOP.md](README_DESKTOP.md) for more details
- Customize settings in `%USERPROFILE%\.localrss\config.json`
- Share the `dist\LocalRSS\` folder with others (no build needed!)

---

**Note**: You only need to build once! After building, you can copy the entire `dist\LocalRSS\` folder to any Windows computer and run it without Python installed.


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
