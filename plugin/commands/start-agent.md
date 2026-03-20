---
description: Start the cowork-mail headless Claude loop in the current workspace
argument-hint: [poll-seconds]
---

Start the cowork-mail autonomous headless loop from the current workspace.

- If the user provided a poll interval as `$1`, use it.
- Otherwise default to `10`.
- Before starting the loop, remind the user that the `cowork-mail` custom connector must already be added manually in Cowork with their private MCP URL.
- Use Bash to run the loop from the current workspace with:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/headless_mail_loop.py" --workspace-dir "$PWD" --poll-seconds "${1:-10}"
```

- Tell the user the exact command you are running before you run it.
- After starting it, tell the user that logs are written under `~/.claude/cowork/run/` and status is written under `~/.claude/cowork/state/`.
- After starting it, confirm that it is a long-running background-style loop that repeatedly invokes `claude -p` from this workspace.
