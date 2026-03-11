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
    resolve_mail_server_url,
    start_detached_watcher,
    workspace_mount,
)


def main() -> int:
    try:
        persona = load_persona()
        ensure_persona_fields(persona)

        persona_id = str(persona["persona_id"])
        display_name = str(persona.get("display_name") or persona_id)
        mail_server_url = resolve_mail_server_url(persona)
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

    except (FileNotFoundError, ValueError):
        # Prefer workspace mount (persists across Cowork sessions)
        ws = workspace_mount()
        if ws:
            persona_path = str(ws / ".cowork-mail" / "persona.json")
        else:
            persona_path = str(Path.home() / ".claude" / "cowork" / "persona.json")
        print("[cowork-mail] SETUP_REQUIRED")
        print("[cowork-mail]")
        print("[cowork-mail] The cowork-mail plugin needs a persona configuration.")
        print("[cowork-mail] Ask the user for the following values, then write the")
        print(f"[cowork-mail] config as JSON to: {persona_path}")
        print("[cowork-mail]")
        print("[cowork-mail] Required fields to ask for:")
        print("[cowork-mail]   - persona_id: a unique name for this agent (e.g. 'marko', 'sara')")
        print("[cowork-mail]   - display_name: friendly name shown in messages")
        print("[cowork-mail]   - role: what this agent does (e.g. 'backend-dev', 'designer')")
        print("[cowork-mail]   - team: list of other persona_ids to collaborate with")
        print("[cowork-mail]")
        print("[cowork-mail] Use these defaults (do not ask the user for these):")
        print("[cowork-mail]   mail_server_url: set COWORK_MAIL_SERVER_URL in the environment, or add it to persona.json")
        print("[cowork-mail]   poll_interval_seconds: 30")
        print('[cowork-mail]   instructions: ["Coordinate via cowork mail for reviews, handoffs, and dependency requests.", "When notified of unread mail, fetch inbox before making conflicting changes."]')
        print("[cowork-mail]")
        print("[cowork-mail] After writing the file, re-run this script to complete bootstrap.")
        return 0

    except Exception as exc:
        print(f"[cowork-mail] Bootstrap error: {exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
