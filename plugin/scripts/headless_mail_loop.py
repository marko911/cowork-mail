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
    log_file,
    load_persona,
    now_ts,
    plugin_root,
    register_persona_api,
    resolve_mail_server_url,
    write_json,
    safe_error_message,
    unread_count,
    watch_dir,
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
        help="How often to run claude -p.",
    )
    parser.add_argument(
        "--only-if-unread",
        action="store_true",
        help="Only invoke claude -p when the mail server reports unread mail.",
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
            f"1. Check your cowork-mail inbox for persona_id '{persona_id}'.",
            "2. If there are unread messages, fetch them and determine what work is requested.",
            "3. Perform the requested work in this workspace when appropriate.",
            f"4. Send replies with send_message using from_persona '{persona_id}'.",
            f"5. Acknowledge handled messages with ack_message or ack_all for persona_id '{persona_id}'.",
            "6. If there is no unread mail, exit quickly without doing extra work.",
            "7. Exit after the unread inbox is drained or there is no actionable work.",
            "Do not ask a human for kickoff. Operate as an autonomous worker for this pass.",
        ]
    )


def status_path(persona_id: str, workspace_dir: Path) -> Path:
    return watch_dir(persona_id, workspace_dir) / "headless-status.json"


def append_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(message.rstrip() + "\n")


def log_event(path: Path, event: str, **fields: object) -> None:
    payload = {"timestamp": now_ts(), "event": event, **fields}
    append_log(path, json.dumps(payload, ensure_ascii=False))


def run_claude(
    workspace_dir: Path,
    persona: dict[str, object],
    mail_server_url: str,
    permission_mode: str,
    model: str,
    loop_log: Path,
) -> tuple[int, str, str]:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        message = "[cowork-mail] Headless loop error: 'claude' command not found"
        print(message)
        append_log(loop_log, message)
        return 127, "", message

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
    log_event(
        loop_log,
        "claude_start",
        workspace_dir=str(workspace_dir),
        command=cmd[:-1],
        persona_id=str(persona["persona_id"]),
    )
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
        append_log(loop_log, "----- claude stdout begin -----")
        append_log(loop_log, result.stdout.rstrip())
        append_log(loop_log, "----- claude stdout end -----")
    if result.stderr.strip():
        print(result.stderr.rstrip(), file=sys.stderr)
        append_log(loop_log, "----- claude stderr begin -----")
        append_log(loop_log, result.stderr.rstrip())
        append_log(loop_log, "----- claude stderr end -----")
    log_event(
        loop_log,
        "claude_exit",
        exit_code=result.returncode,
        workspace_dir=str(workspace_dir),
    )
    return result.returncode, result.stdout, result.stderr


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

    loop_log = log_file(f"{persona_id}-headless", workspace_dir)
    loop_status = status_path(persona_id, workspace_dir)
    start_message = f"[cowork-mail] Headless loop log: {loop_log}"
    print(start_message)
    append_log(loop_log, start_message)
    log_event(
        loop_log,
        "loop_start",
        workspace_dir=str(workspace_dir),
        persona_id=persona_id,
        poll_seconds=max(5, args.poll_seconds),
        model=args.model,
    )

    while True:
        try:
            unread = None
            latest_message_id = ""
            if args.only_if_unread:
                status = unread_count(mail_server_url, persona_id)
                unread = int(status.get("unread", 0))
                latest_message_id = str(status.get("latest_message_id", ""))
                print(
                    f"[cowork-mail] Poll unread={unread} latest={latest_message_id or '-'} "
                    f"workspace={workspace_dir}"
                )
                log_event(
                    loop_log,
                    "poll",
                    unread=unread,
                    latest_message_id=latest_message_id,
                    workspace_dir=str(workspace_dir),
                )
                if unread <= 0:
                    write_json(
                        loop_status,
                        {
                            "timestamp": now_ts(),
                            "persona_id": persona_id,
                            "workspace_dir": str(workspace_dir),
                            "state": "idle",
                            "unread": unread,
                            "latest_message_id": latest_message_id,
                        },
                    )
                    if args.once:
                        return 0
                    time.sleep(max(5, args.poll_seconds))
                    continue
            else:
                print(f"[cowork-mail] Poll workspace={workspace_dir}")
                log_event(loop_log, "poll", workspace_dir=str(workspace_dir))

            write_json(
                loop_status,
                {
                    "timestamp": now_ts(),
                    "persona_id": persona_id,
                    "workspace_dir": str(workspace_dir),
                    "state": "running",
                    "unread": unread,
                    "latest_message_id": latest_message_id,
                },
            )

            code, stdout, stderr = run_claude(
                workspace_dir,
                persona,
                mail_server_url,
                args.permission_mode,
                args.model,
                loop_log,
            )
            print(f"[cowork-mail] claude -p exited with code {code}")
            write_json(
                loop_status,
                {
                    "timestamp": now_ts(),
                    "persona_id": persona_id,
                    "workspace_dir": str(workspace_dir),
                    "state": "completed",
                    "unread": unread,
                    "latest_message_id": latest_message_id,
                    "last_exit_code": code,
                    "last_stdout_preview": stdout[-1000:] if stdout else "",
                    "last_stderr_preview": stderr[-1000:] if stderr else "",
                },
            )

            if args.once:
                return 0

        except KeyboardInterrupt:
            log_event(loop_log, "loop_interrupt", workspace_dir=str(workspace_dir))
            return 130
        except Exception as exc:
            message = safe_error_message(exc)
            print(f"[cowork-mail] Headless loop error: {message}")
            log_event(loop_log, "loop_error", error=message, workspace_dir=str(workspace_dir))
            write_json(
                loop_status,
                {
                    "timestamp": now_ts(),
                    "persona_id": persona_id,
                    "workspace_dir": str(workspace_dir),
                    "state": "error",
                    "error": message,
                },
            )
            if args.once:
                return 1

        time.sleep(max(5, args.poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
