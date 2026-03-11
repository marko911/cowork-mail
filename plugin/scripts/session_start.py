from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    append_exports_to_claude_env,
    ensure_persona_fields,
    load_persona,
    log_file,
    pid_file,
    plugin_root,
    process_alive,
    register_persona_api,
    start_detached_watcher,
)


def main() -> int:
    try:
        persona = load_persona()
        ensure_persona_fields(persona)

        persona_id = str(persona["persona_id"])
        display_name = str(persona.get("display_name") or persona_id)
        mail_server_url = str(persona["mail_server_url"]).rstrip("/")
        poll_interval = int(persona.get("poll_interval_seconds", 30))
        team = persona.get("team", [])
        role = persona.get("role", "")
        instructions = persona.get("instructions", [])
        append_exports_to_claude_env(
            {
                "COWORK_PERSONA_ID": persona_id,
                "COWORK_DISPLAY_NAME": display_name,
                "COWORK_MAIL_SERVER_URL": mail_server_url,
                "COWORK_POLL_INTERVAL_SECONDS": str(poll_interval),
                "COWORK_PERSONA_PATH": str(persona["_persona_path"]),
            }
        )

        register_persona_api(mail_server_url, persona_id, display_name)

        pf = pid_file(persona_id)
        lf = log_file(persona_id)

        pid = -1
        if pf.exists():
            try:
                pid = int(pf.read_text(encoding="utf-8").strip())
            except Exception:
                pid = -1

        if not process_alive(pid):
            script = plugin_root() / "scripts" / "mail_watcher.py"
            watcher_args = [
                sys.executable,
                str(script),
                mail_server_url,
                persona_id,
                str(poll_interval),
            ]
            new_pid = start_detached_watcher(watcher_args, lf, lf)
            pf.write_text(str(new_pid), encoding="utf-8")
            watcher_status = "started"
        else:
            watcher_status = "already running"

        team_str = ", ".join(team) if team else "none configured"
        print(f"[cowork-mail] Persona: {persona_id} ({display_name})")
        print(f"[cowork-mail] Role: {role or 'unset'} | Team: {team_str}")
        print(f"[cowork-mail] Mail watcher: {watcher_status} (every {poll_interval}s)")
        for inst in instructions:
            print(f"[cowork-mail] {inst}")
        print("[cowork-mail] Use send_message/fetch_inbox MCP tools to communicate.")
        return 0

    except Exception as exc:
        print(f"[cowork-mail] Bootstrap error: {exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
