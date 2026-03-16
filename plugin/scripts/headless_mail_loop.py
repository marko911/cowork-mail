from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    ensure_persona_fields,
    load_persona,
    log_file,
    now_ts,
    plugin_root,
    read_json,
    register_persona_api,
    resolve_mail_server_url,
    safe_error_message,
    unread_count,
    watch_dir,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Poll cowork-mail and launch claude -p from the workspace directory."
    )
    parser.add_argument(
        "--workspace-dir",
        default=str(Path.cwd()),
        help="Workspace directory to run claude -p from. Defaults to the current working directory.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=10,
        help="How often to poll unread mail.",
    )
    parser.add_argument(
        "--stuck-retrigger-seconds",
        type=int,
        default=60,
        help="Re-run claude -p for the same unread message after this many seconds.",
    )
    parser.add_argument(
        "--permission-mode",
        default="bypassPermissions",
        help="Permission mode passed to claude -p.",
    )
    parser.add_argument(
        "--model",
        default="sonnet",
        help="Model alias passed to claude -p.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Poll once and exit.",
    )
    return parser.parse_args()


def loop_state_path(persona_id: str) -> Path:
    return watch_dir(persona_id) / "headless-loop.json"


def build_prompt(persona: dict[str, object]) -> str:
    persona_id = str(persona["persona_id"])
    display_name = str(persona.get("display_name") or persona_id)
    role = str(persona.get("role") or "unset")
    team = persona.get("team") or []
    team_str = ", ".join(str(x) for x in team) if team else "none"
    return "\n".join(
        [
            f"You are the headless cowork-mail worker for persona '{persona_id}' ({display_name}).",
            f"Role: {role}. Team: {team_str}.",
            "Run inside the current workspace and process cowork-mail autonomously.",
            "Steps:",
            f"1. Use fetch_inbox for persona_id '{persona_id}' with unread_only=true.",
            "2. Read each unread message payload and determine what work is requested.",
            "3. Perform the requested work in this workspace when appropriate.",
            f"4. Send replies with send_message using from_persona '{persona_id}'.",
            f"5. Acknowledge handled messages with ack_message or ack_all for persona_id '{persona_id}'.",
            "6. Exit after the unread inbox is drained or there is no actionable work.",
            "Do not ask a human for kickoff. Operate as an autonomous worker for this pass.",
        ]
    )


def run_claude(
    workspace_dir: Path,
    persona: dict[str, object],
    mail_server_url: str,
    permission_mode: str,
    model: str,
) -> int:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        print("[cowork-mail] Headless loop error: 'claude' command not found")
        return 127

    root = plugin_root()
    prompt = build_prompt(persona)
    env = os.environ.copy()
    env["COWORK_MAIL_SERVER_URL"] = mail_server_url
    env["COWORK_PERSONA_ID"] = str(persona["persona_id"])
    env["COWORK_DISPLAY_NAME"] = str(persona.get("display_name") or persona["persona_id"])

    cmd = [
        claude_bin,
        "-p",
        "--model",
        model,
        "--permission-mode",
        permission_mode,
        "--setting-sources",
        "project,user,local",
        "--plugin-dir",
        str(root),
        prompt,
    ]

    print(f"[cowork-mail] Launching claude -p from {workspace_dir}")
    print(f"[cowork-mail] Command: {' '.join(cmd[:-1])} <prompt>")
    result = subprocess.run(
        cmd,
        cwd=str(workspace_dir),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.stdout.strip():
        print(result.stdout.rstrip())
    if result.stderr.strip():
        print(result.stderr.rstrip(), file=sys.stderr)
    return result.returncode


def should_invoke(
    state: dict[str, object],
    latest_message_id: str,
    unread: int,
    stuck_retrigger_seconds: int,
) -> bool:
    if unread <= 0:
        return False
    last_latest = str(state.get("latest_message_id") or "")
    last_invoked_at = int(state.get("last_invoked_at") or 0)
    if latest_message_id != last_latest:
        return True
    return now_ts() - last_invoked_at >= stuck_retrigger_seconds


def main() -> int:
    args = parse_args()
    workspace_dir = Path(args.workspace_dir).resolve()

    try:
        persona = load_persona(workspace_dir)
        ensure_persona_fields(persona)
        mail_server_url = resolve_mail_server_url(persona)
        persona_id = str(persona["persona_id"])
        display_name = str(persona.get("display_name") or persona_id)
        register_persona_api(mail_server_url, persona_id, display_name)
    except Exception as exc:
        print(f"[cowork-mail] Headless loop bootstrap error: {safe_error_message(exc)}")
        return 1

    state_path = loop_state_path(persona_id)
    loop_log = log_file(f"{persona_id}-headless")

    while True:
        try:
            status = unread_count(mail_server_url, persona_id)
            unread = int(status.get("unread", 0))
            latest_message_id = str(status.get("latest_message_id", ""))
            state = read_json(state_path, default={}) or {}

            print(
                f"[cowork-mail] Poll unread={unread} latest={latest_message_id or '-'} "
                f"workspace={workspace_dir}"
            )

            if should_invoke(
                state,
                latest_message_id,
                unread,
                args.stuck_retrigger_seconds,
            ):
                code = run_claude(
                    workspace_dir,
                    persona,
                    mail_server_url,
                    args.permission_mode,
                    args.model,
                )
                write_json(
                    state_path,
                    {
                        "timestamp": now_ts(),
                        "latest_message_id": latest_message_id,
                        "last_invoked_at": now_ts(),
                        "last_exit_code": code,
                        "workspace_dir": str(workspace_dir),
                    },
                )
                with loop_log.open("a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {
                                "timestamp": now_ts(),
                                "event": "claude-run",
                                "workspace_dir": str(workspace_dir),
                                "latest_message_id": latest_message_id,
                                "unread": unread,
                                "exit_code": code,
                            }
                        )
                        + "\n"
                    )

            if args.once:
                return 0

        except KeyboardInterrupt:
            return 130
        except Exception as exc:
            print(f"[cowork-mail] Headless loop error: {safe_error_message(exc)}")
            if args.once:
                return 1

        time.sleep(max(5, args.poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
