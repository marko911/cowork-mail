---
description: Start the cowork-mail headless Claude loop in the current workspace
argument-hint: [poll-seconds]
---

Start the cowork-mail autonomous headless loop from the current workspace.

- If the user provided a poll interval as `$1`, use it.
- Otherwise default to `10`.
- The loop reads `mail_server_url` from the workspace persona file and generates a temporary MCP config for the spawned `claude -p` process.
- The required value is the mail server base URL, not the `/mcp` endpoint.
- If the persona file is missing `mail_server_url`, tell the user to add it before starting the loop.
- Use Bash to run the loop from the current workspace with:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/headless_mail_loop.py" --workspace-dir "$PWD" --poll-seconds "${1:-10}"
```

- Tell the user the exact command you are running before you run it.
- After starting it, tell the user that logs are written under `./.claude/cowork/run/` in the current workspace and status is written under `./.claude/cowork/state/`.
- After starting it, confirm that it is a long-running background-style loop that repeatedly invokes `claude -p` from this workspace with a runtime-generated MCP config.
