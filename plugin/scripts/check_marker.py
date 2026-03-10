from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import marker_file


def main() -> int:
    persona_id = os.environ.get("COWORK_PERSONA_ID", "").strip()
    if not persona_id:
        return 0

    path = marker_file(persona_id)
    if not path.exists():
        return 0

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        count = int(data.get("unread", 0))
    except Exception:
        count = 1

    if count > 0:
        print(
            f"[cowork-mail] You have {count} unread message(s). "
            "Use fetch_inbox to check your mail before continuing."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
