---
name: mail-bootstrap
description: >
  Initialize the cowork-mail messaging system for this session.
  Starts the background mail watcher if persona config exists.
  Run this skill when starting a new session or when the user
  mentions cowork-mail, messaging, or checking mail.
---

# Cowork Mail Bootstrap

Set up the cowork-mail messaging system for the current session.

## Steps

### 1. Run the bootstrap script

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/session_start.py"
```

If `CLAUDE_PLUGIN_ROOT` is not set, find the script:

```bash
SCRIPT=$(find / -path "*/cowork-mail/scripts/session_start.py" 2>/dev/null | head -1) && python3 "$SCRIPT"
```

### 2. Interpret the output

- If you see `[cowork-mail] Persona: ...` — bootstrap succeeded, the mail watcher is running.
- If you see `[cowork-mail] SETUP_REQUIRED` — persona config is missing. Ask the user for persona_id, display_name, role, and team. Write the JSON file to the exact path shown in the output. Then re-run the bootstrap script to start the mail watcher.
- If you see `[cowork-mail] Bootstrap error: ...` — report the error.
