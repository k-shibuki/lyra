#!/bin/bash
# Test Command Handlers Loader
#
# This file loads all test command handler modules.
# It maintains the same interface as before, allowing scripts/test.sh
# and scripts/test_scripts.sh to source this file without changes.

# Load command handlers in dependency order
# shellcheck source=/dev/null
source "${BASH_SOURCE[0]%/*}/commands/run.sh"
# shellcheck source=/dev/null
source "${BASH_SOURCE[0]%/*}/commands/env.sh"
# shellcheck source=/dev/null
source "${BASH_SOURCE[0]%/*}/commands/check.sh"
# shellcheck source=/dev/null
source "${BASH_SOURCE[0]%/*}/commands/kill.sh"
# shellcheck source=/dev/null
source "${BASH_SOURCE[0]%/*}/commands/debug.sh"
# shellcheck source=/dev/null
source "${BASH_SOURCE[0]%/*}/commands/help.sh"
