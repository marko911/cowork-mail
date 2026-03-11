from __future__ import annotations

import shutil
import stat
import sys
from pathlib import Path


def copytree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def make_executable_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".sh", ".ps1"}:
            mode = path.stat().st_mode
            path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main() -> int:
    plugin_src = Path(__file__).resolve().parent.parent
    plugin_dst = Path.home() / ".claude" / "plugins" / "cowork-mail"
    persona_dir = Path.home() / ".claude" / "cowork"
    persona_dst = persona_dir / "persona.json"

    plugin_dst.parent.mkdir(parents=True, exist_ok=True)
    persona_dir.mkdir(parents=True, exist_ok=True)

    print(f"Installing plugin to: {plugin_dst}")
    copytree(plugin_src, plugin_dst)
    make_executable_tree(plugin_dst)

    if not persona_dst.exists():
        shutil.copy2(plugin_dst / "templates" / "persona.json", persona_dst)
        print(f"Created template persona file at {persona_dst}")
        print("Edit this file with your persona_id and display details.")
        print("Set COWORK_MAIL_SERVER_URL in the environment or add mail_server_url to the persona file.")
    else:
        print(f"Persona file already exists at {persona_dst}")

    print()
    print("Next steps:")
    print(f"  1. Edit {persona_dst} with your persona config")
    print("  2. Set COWORK_MAIL_SERVER_URL in the environment, unless it is stored in the persona file")
    print("  3. Start a new Claude Code session — the plugin will auto-bootstrap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
