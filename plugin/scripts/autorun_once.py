from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ensure_persona_fields, load_persona, process_alive, run_root, workspace_mount


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one bounded cowork-mail headless pass from a hook."
    )
    parser.add_argument(
        "--workspace-dir",
        default=os.environ.get("CLAUDE_PROJECT_DIR") or str(Path.cwd()),
        help="Workspace directory to run from.",
    )
    parser.add_argument(
        "--reason",
        default="hook",
        help="Hook reason for logging.",
    )
    parser.add_argument(
        "--claude-timeout-seconds",
        type=int,
        default=120,
        help="Maximum time for the nested claude -p pass.",
    )
    return parser.parse_args()


def autorun_pid_path(persona_id: str, workspace_dir: Path) -> Path:
    return run_root(workspace_dir) / f"{persona_id}-autorun.pid"


def main() -> int:
    if os.environ.get("COWORK_MAIL_AUTORUN_DISABLED") == "1":
        return 0

    args = parse_args()
    workspace_dir = Path(args.workspace_dir).resolve()
    mounted_workspace = workspace_mount(workspace_dir)
    if mounted_workspace:
        workspace_dir = mounted_workspace.resolve()

    try:
        persona = load_persona(workspace_dir)
        ensure_persona_fields(persona)
    except Exception as exc:
        print(f"[cowork-mail] Autorun skipped: {exc}")
        return 0

    persona_id = str(persona["persona_id"])
    pid_path = autorun_pid_path(persona_id, workspace_dir)
    existing_pid = -1
    if pid_path.exists():
        try:
            existing_pid = int(pid_path.read_text(encoding="utf-8").strip())
        except Exception:
            existing_pid = -1

    if process_alive(existing_pid):
        print(f"[cowork-mail] Autorun already active for {persona_id} (PID {existing_pid})")
        return 0

    script = Path(__file__).resolve().parent / "headless_mail_loop.py"
    env = os.environ.copy()
    env["COWORK_MAIL_AUTORUN_DISABLED"] = "1"
    env["COWORK_MAIL_AUTORUN_REASON"] = str(args.reason)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(script),
                "--workspace-dir",
                str(workspace_dir),
                "--once",
                "--claude-timeout-seconds",
                str(max(1, args.claude_timeout_seconds)),
            ],
            cwd=str(workspace_dir),
            env=env,
            check=False,
        )
        return proc.returncode
    finally:
        try:
            pid_path.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
