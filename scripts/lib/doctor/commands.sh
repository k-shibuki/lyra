#!/bin/bash
# Doctor Command Handlers Loader
#
# This file loads all doctor command handler modules.

# Load command handlers in dependency order
# shellcheck source=/dev/null
source "${BASH_SOURCE[0]%/*}/commands/check.sh"
# shellcheck source=/dev/null
source "${BASH_SOURCE[0]%/*}/commands/chrome_fix.sh"

