"""Append a timestamped line to a shared debug log file."""
from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path


def log(hook_name: str, extra: str = "") -> None:
    log_dir = Path.home() / ".claude" / "cowork"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "hooks_debug.log"
    ts = datetime.datetime.now().isoformat()
    pid = os.getpid()
    cwd = os.getcwd()
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "unset")
    persona = os.environ.get("COWORK_PERSONA_ID", "unset")
    line = f"[{ts}] hook={hook_name} pid={pid} cwd={cwd} plugin_root={plugin_root} persona={persona}"
    if extra:
        line += f" | {extra}"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    # Called directly: python3 debug_log.py <hook_name> [extra]
    name = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    extra = sys.argv[2] if len(sys.argv) > 2 else ""
    log(name, extra)
