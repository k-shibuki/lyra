#!/bin/bash
# Start Chrome with remote debugging for Lancet
# Run this on Windows (via PowerShell or WSL interop)

CHROME_PORT="${1:-9222}"
PROFILE_NAME="${2:-Profile-Research}"

# Detect OS
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    # Windows native
    CHROME_PATH="/c/Program Files/Google/Chrome/Application/chrome.exe"
    USER_DATA_DIR="$LOCALAPPDATA/Google/Chrome/User Data"
elif grep -qi microsoft /proc/version 2>/dev/null; then
    # WSL
    CHROME_PATH="/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"
    # Get Windows username for user data dir
    WIN_USER=$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r')
    USER_DATA_DIR="/mnt/c/Users/$WIN_USER/AppData/Local/Google/Chrome/User Data"
else
    # Linux native
    CHROME_PATH=$(which google-chrome || which chromium-browser || which chromium)
    USER_DATA_DIR="$HOME/.config/google-chrome"
fi

if [ ! -f "$CHROME_PATH" ] && [ ! -x "$CHROME_PATH" ]; then
    echo "Error: Chrome not found at $CHROME_PATH"
    exit 1
fi

echo "Starting Chrome with remote debugging..."
echo "  Port: $CHROME_PORT"
echo "  Profile: $PROFILE_NAME"
echo "  User Data Dir: $USER_DATA_DIR"
echo ""

# Start Chrome
"$CHROME_PATH" \
    --remote-debugging-port=$CHROME_PORT \
    --user-data-dir="$USER_DATA_DIR" \
    --profile-directory="$PROFILE_NAME" \
    --no-first-run \
    --no-default-browser-check \
    --disable-background-networking \
    --disable-client-side-phishing-detection \
    --disable-default-apps \
    --disable-hang-monitor \
    --disable-popup-blocking \
    --disable-prompt-on-repost \
    --disable-sync \
    --disable-translate \
    --metrics-recording-only \
    --safebrowsing-disable-auto-update \
    &

echo ""
echo "Chrome started with remote debugging on port $CHROME_PORT"
echo "Connect from Playwright with: chromium.connect_over_cdp('http://localhost:$CHROME_PORT')"

