"""Shared settings. Override any value with an environment variable or a line in .env (KEY=value)."""
import os

import pymysql

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv(path=os.path.join(HERE, ".env")):
    """Minimal .env reader (no extra dependency). Real environment variables win."""
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_NAME = os.environ.get("DB_NAME", "")   # set in .env (not committed)

# Admin user: only used by build_catalog.py / setup to read information_schema.
DB_ADMIN_USER = os.environ.get("DB_ADMIN_USER", "root")
DB_ADMIN_PASSWORD = os.environ.get("DB_ADMIN_PASSWORD", "passwd")

# Read-only user: the ONLY account the app uses to run queries.
DB_RO_USER = os.environ.get("DB_RO_USER", "root")
DB_RO_PASSWORD = os.environ.get("DB_RO_PASSWORD", "passwd")

QUERY_TIMEOUT_MS = int(os.environ.get("TTD_QUERY_TIMEOUT_MS", "30000"))

# Databases the app can switch between (picked per user in the header).
# "proxy" is a remote DB reached through a SOCKS5 proxy (default 127.0.0.1:20234).
# Set the real host/user/name/password in .env.
_proxy = {"label": "Proxy", "host": os.environ.get("DB_PROXY_DB_HOST", ""),
          "port": int(os.environ.get("DB_PROXY_DB_PORT", "3306")),
          "name": os.environ.get("DB_PROXY_NAME", DB_NAME),
          "user": os.environ.get("DB_PROXY_USER", ""),
          "password": os.environ.get("DB_PROXY_PASSWORD", ""),
          "socks5": (os.environ.get("DB_PROXY_SOCKS_HOST", "127.0.0.1"),
                     int(os.environ.get("DB_PROXY_SOCKS_PORT", "20234")))}
DATABASES = {
    "local": {"label": "Local", "host": DB_HOST, "port": DB_PORT, "name": DB_NAME,
              "user": DB_RO_USER, "password": DB_RO_PASSWORD},
    "proxy": _proxy,
}
DEFAULT_DB = os.environ.get("TTD_DEFAULT_DB", "local")


def db_key(key: str | None) -> str:
    return key if key in DATABASES else DEFAULT_DB


def admin_connect():
    return pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_ADMIN_USER, password=DB_ADMIN_PASSWORD,
                           database=DB_NAME, charset="utf8mb4")


def ro_connect(key: str | None = None):
    d = DATABASES[db_key(key)]
    read_timeout = QUERY_TIMEOUT_MS // 1000 + 5
    conn = pymysql.connect(host=d["host"], port=d["port"], user=d["user"], password=d["password"],
                           database=d["name"], charset="utf8mb4", read_timeout=read_timeout,
                           connect_timeout=10, cursorclass=pymysql.cursors.DictCursor,
                           defer_connect=bool(d.get("socks5")))
    if d.get("socks5"):
        # pymysql has no SOCKS support: open the TCP socket through the proxy ourselves, then hand it over.
        # rdns=True lets the proxy side resolve d["host"], so the DB hostname is resolved on the proxy side.
        import socks
        sock = socks.socksocket()
        sock.set_proxy(socks.SOCKS5, d["socks5"][0], d["socks5"][1], rdns=True)
        sock.settimeout(10)
        sock.connect((d["host"], d["port"]))
        sock.settimeout(read_timeout)
        conn.connect(sock)
    return conn
