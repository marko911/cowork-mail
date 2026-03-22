from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import traceback
import time
from pathlib import Path
from threading import Thread

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    ensure_persona_fields,
    log_file,
    load_persona,
    now_ts,
    plugin_root,
    register_persona_if_needed,
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
        "--claude-timeout-seconds",
        type=int,
        default=120,
        help="Maximum time to wait for each claude -p pass before terminating it.",
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


def error_path(persona_id: str, workspace_dir: Path) -> Path:
    return watch_dir(persona_id, workspace_dir) / "headless-last-error.json"


def claude_pid_path(persona_id: str, workspace_dir: Path) -> Path:
    return log_file(f"{persona_id}-claude", workspace_dir).with_suffix(".pid")


def append_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(message.rstrip() + "\n")


def log_event(path: Path, event: str, **fields: object) -> None:
    payload = {"timestamp": now_ts(), "event": event, **fields}
    append_log(path, json.dumps(payload, ensure_ascii=False))


def stream_pipe(pipe, loop_log: Path, section: str, sink) -> str:
    chunks: list[str] = []
    if pipe is None:
        return ""
    append_log(loop_log, f"----- claude {section} begin -----")
    try:
        for line in pipe:
            chunks.append(line)
            text = line.rstrip("\n")
            if text:
                append_log(loop_log, f"[claude {section}] {text}")
            else:
                append_log(loop_log, f"[claude {section}]")
            print(text if text else "", file=sink)
    finally:
        try:
            pipe.close()
        except Exception:
            pass
    append_log(loop_log, f"----- claude {section} end -----")
    return "".join(chunks)


def write_runtime_mcp_config(mail_server_url: str) -> Path:
    payload = {
        "mcpServers": {
            "cowork-mail": {
                "type": "http",
                "url": f"{mail_server_url.rstrip('/')}/mcp",
            }
        }
    }
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="cowork-mail-mcp-",
        suffix=".json",
        delete=False,
    ) as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
        return Path(f.name)


def run_claude(
    workspace_dir: Path,
    persona: dict[str, object],
    mail_server_url: str,
    permission_mode: str,
    model: str,
    claude_timeout_seconds: int,
    loop_log: Path,
    loop_status: Path,
    loop_error: Path,
) -> tuple[int, str, str, bool]:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        message = "[cowork-mail] Headless loop error: 'claude' command not found"
        print(message)
        append_log(loop_log, message)
        write_json(loop_error, {"timestamp": now_ts(), "error": message})
        return 127, "", message, False

    root = plugin_root()
    prompt = build_prompt(persona)
    env = os.environ.copy()
    env["COWORK_MAIL_SERVER_URL"] = mail_server_url
    env["COWORK_PERSONA_ID"] = str(persona["persona_id"])
    env["COWORK_DISPLAY_NAME"] = str(persona.get("display_name") or persona["persona_id"])
    env["COWORK_MAIL_AUTORUN_DISABLED"] = "1"
    runtime_mcp_config = write_runtime_mcp_config(mail_server_url)

    cmd = [
        claude_bin,
        "-p",
        "--model",
        model,
        "--permission-mode",
        permission_mode,
        "--mcp-config",
        str(runtime_mcp_config),
        "--strict-mcp-config",
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
        runtime_mcp_config=str(runtime_mcp_config),
        persona_id=str(persona["persona_id"]),
    )
    proc = None
    stdout_text = ""
    stderr_text = ""
    timed_out = False
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(workspace_dir),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        pid_path = claude_pid_path(str(persona["persona_id"]), workspace_dir)
        pid_path.write_text(str(proc.pid), encoding="utf-8")
        log_event(loop_log, "claude_spawned", pid=proc.pid, workspace_dir=str(workspace_dir))
        write_json(
            loop_status,
            {
                "timestamp": now_ts(),
                "persona_id": str(persona["persona_id"]),
                "workspace_dir": str(workspace_dir),
                "state": "running",
                "child_pid": proc.pid,
            },
        )
        stdout_result: list[str] = [""]
        stderr_result: list[str] = [""]

        stdout_thread = Thread(
            target=lambda: stdout_result.__setitem__(0, stream_pipe(proc.stdout, loop_log, "stdout", sys.stdout)),
            daemon=True,
        )
        stderr_thread = Thread(
            target=lambda: stderr_result.__setitem__(0, stream_pipe(proc.stderr, loop_log, "stderr", sys.stderr)),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        start_ts = time.monotonic()
        last_heartbeat = -5.0
        while True:
            returncode = proc.poll()
            elapsed = time.monotonic() - start_ts
            if returncode is not None:
                break
            if elapsed - last_heartbeat >= 5:
                last_heartbeat = elapsed
                log_event(
                    loop_log,
                    "claude_heartbeat",
                    pid=proc.pid,
                    elapsed_seconds=int(elapsed),
                    timeout_seconds=max(1, claude_timeout_seconds),
                    workspace_dir=str(workspace_dir),
                )
                write_json(
                    loop_status,
                    {
                        "timestamp": now_ts(),
                        "persona_id": str(persona["persona_id"]),
                        "workspace_dir": str(workspace_dir),
                        "state": "running",
                        "child_pid": proc.pid,
                        "child_elapsed_seconds": int(elapsed),
                        "claude_timeout_seconds": max(1, claude_timeout_seconds),
                    },
                )
            if elapsed >= max(1, claude_timeout_seconds):
                timed_out = True
                log_event(
                    loop_log,
                    "claude_timeout",
                    pid=proc.pid,
                    elapsed_seconds=int(elapsed),
                    timeout_seconds=max(1, claude_timeout_seconds),
                    workspace_dir=str(workspace_dir),
                )
                append_log(
                    loop_log,
                    f"[cowork-mail] claude -p timed out after {int(elapsed)}s; terminating PID {proc.pid}",
                )
                proc.terminate()
                try:
                    returncode = proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    append_log(loop_log, f"[cowork-mail] claude -p did not terminate; killing PID {proc.pid}")
                    proc.kill()
                    returncode = proc.wait(timeout=10)
                break
            time.sleep(1)
        stdout_thread.join()
        stderr_thread.join()
        stdout_text = stdout_result[0]
        stderr_text = stderr_result[0]
        log_event(
            loop_log,
            "claude_exit",
            exit_code=returncode,
            pid=proc.pid,
            workspace_dir=str(workspace_dir),
        )
        if returncode != 0:
            write_json(
                loop_error,
                {
                    "timestamp": now_ts(),
                    "error": (
                        f"claude -p timed out after {max(1, claude_timeout_seconds)}s"
                        if timed_out
                        else f"claude -p exited with code {returncode}"
                    ),
                    "pid": proc.pid,
                    "timed_out": timed_out,
                    "stdout_tail": stdout_text[-2000:],
                    "stderr_tail": stderr_text[-2000:],
                },
            )
        elif loop_error.exists():
            loop_error.unlink()
        return returncode, stdout_text, stderr_text, timed_out
    except Exception as exc:
        details = safe_error_message(exc)
        append_log(loop_log, f"[cowork-mail] Headless loop child-launch error: {details}")
        append_log(loop_log, traceback.format_exc().rstrip())
        write_json(
            loop_error,
            {
                "timestamp": now_ts(),
                "error": details,
                "traceback": traceback.format_exc(),
            },
        )
        log_event(loop_log, "claude_launch_error", error=details, workspace_dir=str(workspace_dir))
        return 1, stdout_text, f"{stderr_text}\n{details}".strip(), False
    finally:
        try:
            runtime_mcp_config.unlink(missing_ok=True)
        except Exception:
            pass
        if proc is not None:
            try:
                claude_pid_path(str(persona["persona_id"]), workspace_dir).unlink(missing_ok=True)
            except Exception:
                pass


def main() -> int:
    args = parse_args()
    workspace_dir = Path(args.workspace_dir).resolve()

    try:
        persona = load_persona(workspace_dir)
        ensure_persona_fields(persona)
        mail_server_url = resolve_mail_server_url(persona)
        persona_id = str(persona["persona_id"])
        display_name = str(persona.get("display_name") or persona_id)
        register_persona_if_needed(mail_server_url, persona)
    except Exception as exc:
        print(f"[cowork-mail] Headless loop bootstrap error: {safe_error_message(exc)}")
        return 1

    loop_log = log_file(f"{persona_id}-headless", workspace_dir)
    loop_status = status_path(persona_id, workspace_dir)
    loop_error = error_path(persona_id, workspace_dir)
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
        claude_timeout_seconds=max(1, args.claude_timeout_seconds),
    )

    def handle_signal(signum: int, _frame) -> None:
        signame = signal.Signals(signum).name
        log_event(loop_log, "loop_signal", signal=signame, workspace_dir=str(workspace_dir))
        write_json(
            loop_error,
            {
                "timestamp": now_ts(),
                "error": f"headless loop received signal {signame}",
                "workspace_dir": str(workspace_dir),
            },
        )
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        try:
            signal.signal(sig, handle_signal)
        except Exception:
            pass

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

            code, stdout, stderr, timed_out = run_claude(
                workspace_dir,
                persona,
                mail_server_url,
                args.permission_mode,
                args.model,
                args.claude_timeout_seconds,
                loop_log,
                loop_status,
                loop_error,
            )
            print(f"[cowork-mail] claude -p exited with code {code}")
            write_json(
                loop_status,
                {
                    "timestamp": now_ts(),
                    "persona_id": persona_id,
                    "workspace_dir": str(workspace_dir),
                    "state": "timed_out" if timed_out else "completed",
                    "unread": unread,
                    "latest_message_id": latest_message_id,
                    "last_exit_code": code,
                    "timed_out": timed_out,
                    "last_stdout_preview": stdout[-1000:] if stdout else "",
                    "last_stderr_preview": stderr[-1000:] if stderr else "",
                },
            )

            if args.once:
                return 0

        except KeyboardInterrupt:
            log_event(loop_log, "loop_interrupt", workspace_dir=str(workspace_dir))
            write_json(
                loop_error,
                {
                    "timestamp": now_ts(),
                    "error": "headless loop interrupted",
                    "workspace_dir": str(workspace_dir),
                },
            )
            return 130
        except Exception as exc:
            message = safe_error_message(exc)
            print(f"[cowork-mail] Headless loop error: {message}")
            log_event(loop_log, "loop_error", error=message, workspace_dir=str(workspace_dir))
            append_log(loop_log, traceback.format_exc().rstrip())
            write_json(
                loop_error,
                {
                    "timestamp": now_ts(),
                    "persona_id": persona_id,
                    "workspace_dir": str(workspace_dir),
                    "error": message,
                    "traceback": traceback.format_exc(),
                },
            )
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
