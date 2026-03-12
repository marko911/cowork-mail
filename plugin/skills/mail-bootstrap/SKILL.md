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
if [ -n "$CLAUDE_PLUGIN_ROOT" ] && [ -f "$CLAUDE_PLUGIN_ROOT/scripts/session_start.py" ]; then
  python3 "$CLAUDE_PLUGIN_ROOT/scripts/session_start.py"
else
  SCRIPT=$(
    find "$HOME/.claude/plugins" \
      -path "*/cowork-mail/*/scripts/session_start.py" \
      -o -path "*/cowork-mail/scripts/session_start.py" \
      2>/dev/null | head -1
  )
  if [ -n "$SCRIPT" ] && [ -f "$SCRIPT" ]; then
    python3 "$SCRIPT"
  else
    echo "[cowork-mail] Bootstrap error: session_start.py not found"
    echo "[cowork-mail] Checked CLAUDE_PLUGIN_ROOT and ~/.claude/plugins for the installed plugin."
  fi
fi
```

### 2. Interpret the output

- If you see `[cowork-mail] Persona: ...` — bootstrap succeeded, the mail watcher is running.
- If you see `[cowork-mail] SETUP_REQUIRED` — persona config is missing. Ask the user for persona_id, display_name, role, and team. Write the JSON file to the exact path shown in the output. Then re-run the bootstrap script to start the mail watcher.
- If you see `[cowork-mail] Bootstrap error: ...` — report the error.
