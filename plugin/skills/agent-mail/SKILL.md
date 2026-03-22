---
name: agent-mail
description: >
  Use cowork-mail autonomously for the current workspace by loading the persona
  from ./.claude/cowork/persona.json, checking inbox, doing requested work,
  replying, and acknowledging handled messages. Use this for scheduled tasks.
---

# Agent Mail

Use cowork-mail for the current workspace, but only with the persona configured
in the workspace itself.

## Required contract

- Read `./.claude/cowork/persona.json` first.
- Extract `persona_id`, `display_name`, and `mail_server_url` from that file.
- Never invent a persona like `marko-assistant`.
- Never use a persona from memory or from a previous run.
- If `./.claude/cowork/persona.json` is missing or invalid, stop and report that.
- Use the exact `persona_id` from the file for all cowork-mail tool calls.

## Required cowork-mail flow

1. Read `./.claude/cowork/persona.json`.
2. If present and valid, call `register_persona` with:
   - `persona_id` from the file
   - `display_name` from the file, or the `persona_id` if missing
3. Call `get_unread_count` with that same `persona_id`.
4. If unread count is zero:
   - say the inbox is clear for that exact `persona_id`
   - do not invent a different persona
   - exit quickly
5. If unread count is greater than zero:
   - call `fetch_inbox` with that exact `persona_id`
   - inspect the unread messages
   - do the requested work in the current workspace when appropriate
   - if you create files, save them in the current workspace/context directory
   - reply with `send_message` using `from_persona` equal to that same `persona_id`
   - acknowledge handled messages with `ack_message` or `ack_all` using that same `persona_id`

## Forbidden behavior

- Do not call `register_persona` with a persona that is not in `./.claude/cowork/persona.json`.
- Do not use `marko-assistant` unless the persona file explicitly says `marko-assistant`.
- Do not skip reading the persona file at the start of the run.
- Do not check mail for any persona other than the one loaded from the workspace file.
