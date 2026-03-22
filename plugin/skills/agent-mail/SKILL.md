---
name: agent-mail
description: >
  Use cowork-mail autonomously for the current workspace by loading the persona
  from the selected workspace, checking inbox, doing requested work, replying,
  and acknowledging handled messages. Use this for scheduled tasks.
---

# Agent Mail

Use cowork-mail for the current workspace, but only with the persona configured
in the workspace itself.

## Required contract

- Read the persona file from the selected workspace before using any cowork-mail tool.
- Try these candidate paths in order and use the first one that exists:
  1. `./.claude/cowork/persona.json`
  2. `./claude-workspace/.claude/cowork/persona.json`
  3. `./mnt/claude-workspace/.claude/cowork/persona.json`
- Extract `persona_id`, `display_name`, and `mail_server_url` from that file.
- Never invent a persona like `marko-assistant`.
- Never use a persona from memory or from a previous run.
- If none of those persona files exists or the file is invalid, stop and report that.
- Use the exact `persona_id` from the file for all cowork-mail tool calls.

## Required cowork-mail flow

1. Read the persona file from the selected workspace using the candidate path order above.
2. If the persona file contains `"remote_registered": true`, do not call `register_persona`.
3. Only if the persona file explicitly shows it has not been remotely registered yet, call `register_persona` once with:
   - `persona_id` from the file
   - `display_name` from the file, or the `persona_id` if missing
4. Call `get_unread_count` with that same `persona_id`.
5. If unread count is zero:
   - say the inbox is clear for that exact `persona_id`
   - do not invent a different persona
   - exit quickly
6. If unread count is greater than zero:
   - call `fetch_inbox` with that exact `persona_id`
   - inspect the unread messages
   - do the requested work in the current workspace when appropriate
   - if you create files, save them in the current workspace/context directory
   - reply with `send_message` using `from_persona` equal to that same `persona_id`
   - acknowledge handled messages with `ack_message` or `ack_all` using that same `persona_id`

## Forbidden behavior

- Do not call `register_persona` with a persona that is not in the resolved workspace persona file.
- Do not re-register a persona when the resolved workspace persona file already shows `"remote_registered": true`.
- Do not use `marko-assistant` unless the persona file explicitly says `marko-assistant`.
- Do not skip reading the persona file at the start of the run.
- Do not check mail for any persona other than the one loaded from the workspace file.
