#!/bin/bash
# Chrome Help Functions
#
# Functions for displaying help information.

show_help() {
    echo "Lyra Chrome Manager"
    echo ""
    echo "Usage: $0 [global-options] {check|start|stop|diagnose|fix} [port]"
    echo ""
    echo "Commands:"
    echo "  check     Check if Chrome debug port is available (default)"
    echo "  start     Start Chrome with remote debugging (separate profile)"
    echo "  stop      Stop Lyra Chrome instance"
    echo "  diagnose  Troubleshoot connection issues (WSL only)"
    echo "  fix       Auto-generate fix commands for WSL2 mirrored networking"
    echo ""
    echo "Global Options:"
    echo "  --json        Output in JSON format (machine-readable)"
    echo "  --quiet, -q   Suppress non-essential output"
    echo ""
    echo "Default port: $CHROME_PORT (from .env: LYRA_BROWSER__CHROME_PORT)"
    echo ""
    echo "Examples:"
    echo "  make chrome              # Check status"
    echo "  make chrome-start        # Start Chrome"
    echo "  make chrome-diagnose     # Diagnose issues"
    echo ""
    echo "Exit Codes:"
    echo "  0   (EXIT_SUCCESS)   Chrome is ready"
    echo "  13  (EXIT_NOT_READY) Chrome CDP not responding"
    echo "  31  (EXIT_NETWORK)   Network/connection error"
    echo ""
    echo "The Chrome instance uses a separate profile (LyraChrome)"
    echo "so it won't interfere with your normal browsing."
    echo ""
    echo "WSL2 Note:"
    echo "  WSL2 requires mirrored networking mode for localhost access."
    echo "  Run 'make doctor-chrome-fix' if connection fails after WSL2 update."
}

