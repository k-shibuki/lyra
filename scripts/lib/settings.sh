#!/bin/bash
# Lyra shell - read Python settings (config/settings.yaml + config/local.yaml + env overrides)
#
# Purpose:
# - Avoid duplicating config parsing logic in bash
# - Keep .env minimal (secrets/host-only) while allowing scripts to read runtime config
#
# Requirements:
# - Run from within the repo (PROJECT_DIR set by scripts/lib/paths.sh)
# - Prefer venv python when available

lyra_python() {
    if [[ -x "${VENV_DIR}/bin/python" ]]; then
        echo "${VENV_DIR}/bin/python"
        return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        echo "python3"
        return 0
    fi
    echo "python"
}

# Usage: lyra_get_setting "general.proxy_url"
lyra_get_setting() {
    local path="${1:-}"
    if [[ -z "$path" ]]; then
        return 1
    fi

    local py
    py="$(lyra_python)"

    PYTHONPATH="${PROJECT_DIR}:${PYTHONPATH:-}" "$py" - <<PY
from __future__ import annotations

import sys

from src.utils.config import get_settings

path = ${path!r}
s = get_settings()
cur = s
for part in path.split("."):
    cur = getattr(cur, part)
print(cur)
PY
}

