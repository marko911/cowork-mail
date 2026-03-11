from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    marker_file,
    now_ts,
    platform_notify,
    read_json,
    safe_error_message,
    unread_count,
    unread_state_file,
    watch_dir,
    write_json,
)


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "usage: mail_watcher.py <server> <persona_id> <interval_seconds>",
            file=sys.stderr,
        )
        return 2

    server, persona_id, interval_raw = sys.argv[1:]
    interval = max(5, int(interval_raw))

    wdir = watch_dir(persona_id)
    state_path = unread_state_file(persona_id)
    marker_path = marker_file(persona_id)
    lock_path = wdir / "notified.lock"
    error_path = wdir / "last-error.json"

    while True:
        try:
            result = unread_count(server, persona_id)
            count = int(result.get("unread", 0))
            latest = str(result.get("latest_message_id", ""))

            prev = read_json(state_path, default={}) or {}
            prev_count = int(prev.get("unread", 0))
            prev_latest = str(prev.get("latest_message_id", ""))

            changed = count > 0 and (count != prev_count or latest != prev_latest)

            write_json(state_path, {
                "timestamp": now_ts(),
                "unread": count,
                "latest_message_id": latest,
            })

            if count > 0:
                write_json(marker_path, {
                    "unread_mail": True,
                    "persona_id": persona_id,
                    "timestamp": now_ts(),
                    "unread": count,
                    "latest_message_id": latest,
                })
            else:
                if marker_path.exists():
                    marker_path.unlink()
                if lock_path.exists():
                    lock_path.unlink()

            if changed and not lock_path.exists():
                platform_notify("Cowork Mail", f"{count} unread for {persona_id}")
                lock_path.write_text(str(now_ts()), encoding="utf-8")

            if error_path.exists():
                error_path.unlink()

        except Exception as exc:
            write_json(error_path, {"timestamp": now_ts(), "error": safe_error_message(exc)})

        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
