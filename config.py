"""Shared settings. Override any value with an environment variable."""
import os

import pymysql

DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_NAME = os.environ.get("DB_NAME", "mis_40_50")

# Admin user: only used by build_catalog.py / setup to read information_schema.
DB_ADMIN_USER = os.environ.get("DB_ADMIN_USER", "root")
DB_ADMIN_PASSWORD = os.environ.get("DB_ADMIN_PASSWORD", "")

# Read-only user: the ONLY account the app uses to run queries.
DB_RO_USER = os.environ.get("DB_RO_USER", "talk_to_db_ro")
DB_RO_PASSWORD = os.environ.get("DB_RO_PASSWORD", "talk_to_db_ro_local")

QUERY_TIMEOUT_MS = int(os.environ.get("TTD_QUERY_TIMEOUT_MS", "30000"))


def admin_connect():
    return pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_ADMIN_USER, password=DB_ADMIN_PASSWORD,
                           database=DB_NAME, charset="utf8mb4")


def ro_connect():
    return pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_RO_USER, password=DB_RO_PASSWORD,
                           database=DB_NAME, charset="utf8mb4", read_timeout=QUERY_TIMEOUT_MS // 1000 + 5,
                           cursorclass=pymysql.cursors.DictCursor)
