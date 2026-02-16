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
