"""
Minimal NDJSON debug logger for Cursor debug mode.

Enabled only when LYRA_AGENT_DEBUG=1.
Writes to LYRA_AGENT_DEBUG_LOG_PATH or the default Cursor debug log path.

NOTE: Do not log secrets (API keys, tokens, cookies).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_DEFAULT_LOG_PATH = "/home/statuser/Projects/lyra/.cursor/debug.log"


def agent_debug_enabled() -> bool:
    return os.getenv("LYRA_AGENT_DEBUG", "") == "1"


def agent_debug_log_path() -> str:
    return os.getenv("LYRA_AGENT_DEBUG_LOG_PATH", _DEFAULT_LOG_PATH)


def agent_debug_session_id() -> str:
    return os.getenv("LYRA_AGENT_DEBUG_SESSION_ID", "debug-session")


def agent_debug_run_id() -> str:
    return os.getenv("LYRA_AGENT_DEBUG_RUN_ID", "pre-fix")


def agent_log(
    *,
    sessionId: str,
    runId: str,
    hypothesisId: str,
    location: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    if not agent_debug_enabled():
        return

    payload = {
        "sessionId": sessionId,
        "runId": runId,
        "hypothesisId": hypothesisId,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }

    path = agent_debug_log_path()
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Never break production flow due to debug logging.
        return
