from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    append_exports_to_claude_env,
    ensure_persona_fields,
    load_persona,
    register_persona_api,
    resolve_mail_server_url,
)


def bootstrap_if_needed() -> bool:
    """Bootstrap persona on first tool use if SessionStart hook didn't run."""
    persona_id = os.environ.get("COWORK_PERSONA_ID", "").strip()
    if persona_id:
        return True  # already bootstrapped

    try:
        persona = load_persona()
        ensure_persona_fields(persona)
    except (FileNotFoundError, ValueError):
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
        print("[cowork-mail] IMPORTANT: You MUST use the Write tool to create this JSON file.")
        print("[cowork-mail] Do NOT use the register_persona MCP tool instead.")
        print("[cowork-mail] After writing the file, tell the user to start a new session.")
        return False
    except Exception:
        return False

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

    team_str = ", ".join(team) if team else "none configured"
    print(f"[cowork-mail] Persona: {persona_id} ({display_name})")
    print(f"[cowork-mail] Role: {role or 'unset'} | Team: {team_str}")
    for inst in instructions:
        print(f"[cowork-mail] {inst}")
    print("[cowork-mail] Use send_message/fetch_inbox MCP tools to communicate.")

    # Set env for subsequent calls in this session
    os.environ["COWORK_PERSONA_ID"] = persona_id
    return True


def main() -> int:
    if not bootstrap_if_needed():
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
