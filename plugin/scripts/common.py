from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def plugin_root() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def home_claude_dir() -> Path:
    return Path.home() / ".claude"


def state_root() -> Path:
    root = home_claude_dir() / "cowork" / "state"
    root.mkdir(parents=True, exist_ok=True)
    return root


def run_root() -> Path:
    root = home_claude_dir() / "cowork" / "run"
    root.mkdir(parents=True, exist_ok=True)
    return root


def candidate_persona_paths(cwd: Path | None = None) -> list[Path]:
    cwd = cwd or Path.cwd()
    home = Path.home()
    return [
        cwd / ".claude" / "cowork" / "persona.json",
        cwd / ".claude" / "persona.json",
        home / ".claude" / "cowork" / "persona.json",
        home / ".claude" / "persona.json",
    ]


def load_persona(cwd: Path | None = None) -> dict[str, Any]:
    for path in candidate_persona_paths(cwd):
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_persona_path"] = str(path)
            return data
    raise FileNotFoundError(
        "persona file not found in: "
        + ", ".join(str(p) for p in candidate_persona_paths(cwd))
    )


def ensure_persona_fields(data: dict[str, Any]) -> None:
    required = ["persona_id", "mail_server_url"]
    missing = [k for k in required if not data.get(k)]
    if not data.get("mail_api_token") and not data.get("mail_api_token_env"):
        missing.append("mail_api_token (or mail_api_token_env)")
    if missing:
        raise ValueError(f"missing required persona fields: {', '.join(missing)}")


def safe_key(persona_id: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in persona_id)


def watch_dir(persona_id: str) -> Path:
    p = state_root() / safe_key(persona_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def marker_file(persona_id: str) -> Path:
    return watch_dir(persona_id) / "marker.json"


def unread_state_file(persona_id: str) -> Path:
    return watch_dir(persona_id) / "unread-state.json"


def pid_file(persona_id: str) -> Path:
    return run_root() / f"{safe_key(persona_id)}.pid"


def log_file(persona_id: str) -> Path:
    return run_root() / f"{safe_key(persona_id)}.log"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def http_get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    req = Request(url, headers=headers, method="GET")
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_json(
    url: str, headers: dict[str, str], payload: dict[str, Any]
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = Request(url, headers=headers, data=body, method="POST")
    with urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8").strip()
        return json.loads(raw) if raw else {"ok": True}


def unread_count(server: str, persona_id: str, token: str) -> dict[str, Any]:
    server = server.rstrip("/")
    query = urlencode({"persona_id": persona_id})
    url = f"{server}/api/unread?{query}"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    return http_get_json(url, headers)


def register_persona_api(
    server: str, persona_id: str, display_name: str, token: str
) -> None:
    server = server.rstrip("/")
    url = f"{server}/api/register"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {"persona_id": persona_id, "display_name": display_name or persona_id}
    try:
        http_post_json(url, headers, payload)
    except Exception:
        pass


def resolve_token(persona: dict[str, Any]) -> str:
    # Direct token in persona.json takes priority
    direct = persona.get("mail_api_token", "")
    if direct:
        return str(direct)
    # Fall back to env var for power users
    env_name = persona.get("mail_api_token_env", "")
    if env_name:
        token = os.environ.get(str(env_name), "")
        if token:
            return token
    raise RuntimeError(
        "No token found. Set mail_api_token in persona.json "
        "or mail_api_token_env pointing to an environment variable."
    )


def append_exports_to_claude_env(exports: dict[str, str]) -> None:
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not env_file:
        return
    path = Path(env_file)
    lines = []
    for k, v in exports.items():
        escaped = v.replace("\\", "\\\\").replace("'", "\\'")
        lines.append(f"export {k}='{escaped}'")
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, check=False,
            )
            return str(pid) in out.stdout
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start_detached_watcher(
    args: list[str], stdout_path: Path, stderr_path: Path
) -> int:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_f = open(stdout_path, "a", encoding="utf-8")
    stderr_f = open(stderr_path, "a", encoding="utf-8")
    kwargs: dict[str, Any] = {
        "args": args,
        "stdout": stdout_f,
        "stderr": stderr_f,
        "cwd": str(Path.cwd()),
        "env": os.environ.copy(),
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(**kwargs)
    return proc.pid


def platform_notify(title: str, message: str) -> None:
    system = platform.system().lower()
    try:
        if system == "darwin":
            script = (
                f'display notification "{message.replace(chr(34), chr(92)+chr(34))}" '
                f'with title "{title.replace(chr(34), chr(92)+chr(34))}"'
            )
            subprocess.run(["osascript", "-e", script], check=False)
            return
        if system == "linux":
            subprocess.run(["notify-send", title, message], check=False)
            return
    except Exception:
        pass
    try:
        sys.stderr.write(f"\a{title}: {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


def now_ts() -> int:
    return int(time.time())


def safe_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        try:
            return f"http {exc.code}: {exc.read().decode('utf-8', errors='ignore')}"
        except Exception:
            return f"http {exc.code}"
    if isinstance(exc, URLError):
        return str(exc.reason)
    return str(exc)
