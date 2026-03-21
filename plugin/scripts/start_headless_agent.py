from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    ensure_persona_fields,
    load_persona,
    log_file,
    now_ts,
    process_alive,
    run_root,
    start_detached_watcher,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the cowork-mail headless loop in the background."
    )
    parser.add_argument(
        "--workspace-dir",
        default=str(Path.cwd()),
        help="Workspace directory to run the headless loop from.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=10,
        help="Polling interval for the headless loop.",
    )
    return parser.parse_args()


def headless_pid_path(persona_id: str, workspace_dir: Path) -> Path:
    return run_root(workspace_dir) / f"{persona_id}-headless.pid"


def main() -> int:
    args = parse_args()
    workspace_dir = Path(args.workspace_dir).resolve()

    try:
        persona = load_persona(workspace_dir)
        ensure_persona_fields(persona)
    except Exception as exc:
        print(f"[cowork-mail] Start-agent bootstrap error: {exc}")
        return 1

    persona_id = str(persona["persona_id"])
    persona_path = str(persona.get("_persona_path") or "")
    loop_log = log_file(f"{persona_id}-headless", workspace_dir)
    pid_path = headless_pid_path(persona_id, workspace_dir)

    existing_pid = -1
    if pid_path.exists():
        try:
            existing_pid = int(pid_path.read_text(encoding="utf-8").strip())
        except Exception:
            existing_pid = -1

    if process_alive(existing_pid):
        print(f"[cowork-mail] Headless loop already running for {persona_id} (PID {existing_pid})")
        print(f"[cowork-mail] Persona file: {persona_path}")
        print(f"[cowork-mail] Log file: {loop_log}")
        return 0

    script = Path(__file__).resolve().parent / "headless_mail_loop.py"
    child_args = [
        sys.executable,
        str(script),
        "--workspace-dir",
        str(workspace_dir),
        "--poll-seconds",
        str(max(5, args.poll_seconds)),
    ]

    new_pid = start_detached_watcher(child_args, loop_log, loop_log)
    pid_path.write_text(str(new_pid), encoding="utf-8")

    write_json(
        run_root(workspace_dir) / f"{persona_id}-headless-launch.json",
        {
            "timestamp": now_ts(),
            "persona_id": persona_id,
            "persona_path": persona_path,
            "workspace_dir": str(workspace_dir),
            "poll_seconds": max(5, args.poll_seconds),
            "pid": new_pid,
            "log_file": str(loop_log),
        },
    )

    print(f"[cowork-mail] Started headless loop for {persona_id} (PID {new_pid})")
    print(f"[cowork-mail] Persona file: {persona_path}")
    print(f"[cowork-mail] Log file: {loop_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
