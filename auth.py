"""Optional sign-in for the team.

Off until `users.json` exists (create it with `manage_users.py add <name>`). When off, the app is meant to stay on
localhost and the UI says so. When on, every page and API call needs a session, and the audit log records the user.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.environ.get("MIS_USERS_FILE", os.path.join(HERE, "users.json"))
COOKIE = "mis_session"
SESSION_SECONDS = 8 * 3600
PBKDF2_ITERS = 310_000
MAX_FAILS, FAIL_WINDOW = 5, 300   # per IP: 5 failed sign-ins per 5 minutes

_lock = threading.Lock()
_fails: dict[str, list[float]] = {}


def _load() -> dict | None:
    if not os.path.exists(USERS_FILE):
        return None
    with open(USERS_FILE) as f:
        return json.load(f)


def _save(data: dict):
    tmp = USERS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, USERS_FILE)


def enabled() -> bool:
    return os.path.exists(USERS_FILE)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERS)
    return f"pbkdf2_sha256${PBKDF2_ITERS}${salt}${dk.hex()}"


def _check(password: str, stored: str) -> bool:
    try:
        _, iters, salt, want = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), want)
    except ValueError:
        return False


def set_user(name: str, password: str, display: str = ""):
    data = _load() or {"secret": secrets.token_hex(32), "users": {}}
    data["users"][name] = {"hash": hash_password(password), "display": display or name}
    _save(data)


def remove_user(name: str) -> bool:
    data = _load()
    if not data or name not in data["users"]:
        return False
    del data["users"][name]
    _save(data)
    return True


def list_users() -> list[str]:
    data = _load()
    return sorted(data["users"]) if data else []


def rate_limited(ip: str) -> int:
    """Seconds until this IP may try again (0 = allowed)."""
    now = time.time()
    with _lock:
        recent = [t for t in _fails.get(ip, []) if now - t < FAIL_WINDOW]
        _fails[ip] = recent
        return int(FAIL_WINDOW - (now - recent[0])) + 1 if len(recent) >= MAX_FAILS else 0


def login(name: str, password: str, ip: str) -> str | None:
    """Returns a session token, or None."""
    data = _load()
    user = (data or {}).get("users", {}).get(name)
    if not user or not _check(password, user["hash"]):
        with _lock:
            _fails.setdefault(ip, []).append(time.time())
        return None
    with _lock:
        _fails.pop(ip, None)
    exp = int(time.time()) + SESSION_SECONDS
    payload = f"{name}|{exp}"
    sig = hmac.new(data["secret"].encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def session_user(token: str | None) -> dict | None:
    """{'name', 'display'} for a valid, unexpired token whose user still exists."""
    data = _load()
    if not data or not token or token.count("|") != 2:
        return None
    name, exp, sig = token.split("|")
    want = hmac.new(data["secret"].encode(), f"{name}|{exp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, want) or not exp.isdigit() or int(exp) < time.time():
        return None
    user = data["users"].get(name)
    return {"name": name, "display": user.get("display", name)} if user else None
