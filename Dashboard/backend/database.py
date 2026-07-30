"""
Database layer for RustDesk API Server.
SQLite database with tables for users, devices, heartbeats, address books, audit logs, and sessions.
"""

import sqlite3
import os
import time
import json
import hashlib
import secrets
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.db")


def get_db_path():
    return DB_PATH


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize the database schema."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT DEFAULT '',
                email TEXT DEFAULT '',
                is_admin INTEGER DEFAULT 0,
                status INTEGER DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                uuid TEXT DEFAULT '',
                user_id INTEGER,
                hostname TEXT DEFAULT '',
                os TEXT DEFAULT '',
                version TEXT DEFAULT '',
                cpu TEXT DEFAULT '',
                memory TEXT DEFAULT '',
                ip TEXT DEFAULT '',
                status TEXT DEFAULT 'offline',
                last_heartbeat REAL DEFAULT 0,
                first_seen REAL NOT NULL,
                info_json TEXT DEFAULT '{}',
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS heartbeats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                ip TEXT DEFAULT '',
                info_json TEXT DEFAULT '{}',
                FOREIGN KEY (device_id) REFERENCES devices(id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                device_id TEXT DEFAULT '',
                token TEXT UNIQUE NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS address_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                data TEXT DEFAULT '{}',
                updated_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                action TEXT NOT NULL,
                source_id TEXT DEFAULT '',
                source_ip TEXT DEFAULT '',
                target_id TEXT DEFAULT '',
                target_ip TEXT DEFAULT '',
                user_id INTEGER DEFAULT 0,
                conn_id TEXT DEFAULT '',
                session_id TEXT DEFAULT '',
                note TEXT DEFAULT '',
                duration INTEGER DEFAULT 0,
                info_json TEXT DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status);
            CREATE INDEX IF NOT EXISTS idx_devices_user_id ON devices(user_id);
            CREATE INDEX IF NOT EXISTS idx_heartbeats_device_id ON heartbeats(device_id);
            CREATE INDEX IF NOT EXISTS idx_heartbeats_timestamp ON heartbeats(timestamp);
            CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
            CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
            CREATE INDEX IF NOT EXISTS idx_address_books_user_id ON address_books(user_id);
        """)


# ─── User Operations ───

def create_user(username: str, password_hash: str, name: str = "", email: str = "", is_admin: int = 0):
    now = time.time()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, name, email, is_admin, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (username, password_hash, name, email, is_admin, now, now)
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_user_by_username(username: str):
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_user_by_id(user_id: int):
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_all_users():
    with get_db() as conn:
        return conn.execute("SELECT id, username, name, email, is_admin, status, created_at, updated_at FROM users ORDER BY id").fetchall()


def update_user(user_id: int, **kwargs):
    allowed = {"username", "password_hash", "name", "email", "is_admin", "status"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    fields["updated_at"] = time.time()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [user_id]
    with get_db() as conn:
        conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)


def delete_user(user_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


# ─── Device Operations ───

def upsert_device(device_id: str, uuid: str = "", user_id: int = None, hostname: str = "",
                  os_name: str = "", version: str = "", cpu: str = "", memory: str = "",
                  ip: str = "", info: dict = None):
    now = time.time()
    info_json = json.dumps(info or {})
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if existing:
            # Only update fields that have actual values — don't wipe hostname with empty heartbeats
            updates = {"status": "online", "last_heartbeat": now, "info_json": info_json}
            if uuid: updates["uuid"] = uuid
            if hostname: updates["hostname"] = hostname
            if os_name: updates["os"] = os_name
            if version: updates["version"] = version
            if cpu: updates["cpu"] = cpu
            if memory: updates["memory"] = memory
            if ip: updates["ip"] = ip
            
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [device_id]
            conn.execute(f"UPDATE devices SET {set_clause} WHERE id = ?", values)
            
            if user_id is not None:
                conn.execute("UPDATE devices SET user_id=? WHERE id=?", (user_id, device_id))
        else:
            conn.execute("""
                INSERT INTO devices (id, uuid, user_id, hostname, os, version, cpu, memory, ip, status, last_heartbeat, first_seen, info_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'online', ?, ?, ?)
            """, (device_id, uuid, user_id, hostname, os_name, version, cpu, memory, ip, now, now, info_json))


def get_all_devices():
    with get_db() as conn:
        return conn.execute("SELECT * FROM devices ORDER BY last_heartbeat DESC").fetchall()


def get_online_devices():
    with get_db() as conn:
        return conn.execute("SELECT * FROM devices WHERE status = 'online' ORDER BY last_heartbeat DESC").fetchall()


def mark_stale_devices(timeout_seconds: int = 90):
    """Mark devices as offline if they haven't heartbeated within the timeout."""
    cutoff = time.time() - timeout_seconds
    with get_db() as conn:
        conn.execute("UPDATE devices SET status = 'offline' WHERE last_heartbeat < ? AND status = 'online'", (cutoff,))


def get_device_by_id(device_id: str):
    with get_db() as conn:
        return conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()


# ─── Heartbeat Operations ───

def record_heartbeat(device_id: str, ip: str = "", info: dict = None):
    now = time.time()
    info_json = json.dumps(info or {})
    with get_db() as conn:
        conn.execute(
            "INSERT INTO heartbeats (device_id, timestamp, ip, info_json) VALUES (?, ?, ?, ?)",
            (device_id, now, ip, info_json)
        )
        # Keep only last 100 heartbeats per device
        conn.execute("""
            DELETE FROM heartbeats WHERE device_id = ? AND id NOT IN (
                SELECT id FROM heartbeats WHERE device_id = ? ORDER BY timestamp DESC LIMIT 100
            )
        """, (device_id, device_id))


# ─── Session Operations ───

def create_session(user_id: int, device_id: str = "", token: str = "", ttl: int = 86400 * 30):
    now = time.time()
    if not token:
        token = secrets.token_hex(32)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (user_id, device_id, token, created_at, expires_at, is_active) VALUES (?, ?, ?, ?, ?, 1)",
            (user_id, device_id, token, now, now + ttl)
        )
    return token


def get_session_by_token(token: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE token = ? AND is_active = 1", (token,)).fetchone()
        if row and row["expires_at"] > time.time():
            return row
        return None


def invalidate_session(token: str):
    with get_db() as conn:
        conn.execute("UPDATE sessions SET is_active = 0 WHERE token = ?", (token,))


def cleanup_expired_sessions():
    now = time.time()
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))


# ─── Address Book Operations ───

def get_address_book(user_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM address_books WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            return json.loads(row["data"])
        return {}


def set_address_book(user_id: int, data: dict):
    now = time.time()
    data_json = json.dumps(data)
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM address_books WHERE user_id = ?", (user_id,)).fetchone()
        if existing:
            conn.execute("UPDATE address_books SET data = ?, updated_at = ? WHERE user_id = ?", (data_json, now, user_id))
        else:
            conn.execute("INSERT INTO address_books (user_id, data, updated_at) VALUES (?, ?, ?)", (user_id, data_json, now))


# ─── Audit Log Operations ───

def add_audit_log(action: str, source_id: str = "", source_ip: str = "", target_id: str = "",
                  target_ip: str = "", user_id: int = 0, conn_id: str = "", session_id: str = "",
                  note: str = "", duration: int = 0, info: dict = None):
    now = time.time()
    info_json = json.dumps(info or {})
    with get_db() as conn:
        conn.execute("""
            INSERT INTO audit_logs (timestamp, action, source_id, source_ip, target_id, target_ip,
            user_id, conn_id, session_id, note, duration, info_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (now, action, source_id, source_ip, target_id, target_ip, user_id, conn_id, session_id, note, duration, info_json))


def get_audit_logs(limit: int = 100, offset: int = 0, action: str = None):
    with get_db() as conn:
        if action:
            return conn.execute(
                "SELECT * FROM audit_logs WHERE action = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (action, limit, offset)
            ).fetchall()
        return conn.execute(
            "SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()


def get_connection_audit_logs(limit: int = 50):
    """Get connection-type audit logs (who connected to who)."""
    with get_db() as conn:
        return conn.execute("""
            SELECT * FROM audit_logs 
            WHERE action IN ('new_conn', 'close_conn', 'connect', 'disconnect', 'file_transfer')
            ORDER BY timestamp DESC LIMIT ?
        """, (limit,)).fetchall()


# ─── Dashboard Stats ───

def get_dashboard_stats():
    with get_db() as conn:
        total_devices = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        online_devices = conn.execute("SELECT COUNT(*) FROM devices WHERE status = 'online'").fetchone()[0]
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

        today_start = time.time() - (time.time() % 86400)
        connections_today = conn.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action IN ('new_conn', 'connect') AND timestamp >= ?",
            (today_start,)
        ).fetchone()[0]

        active_sessions = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE is_active = 1 AND expires_at > ?",
            (time.time(),)
        ).fetchone()[0]

        return {
            "total_devices": total_devices,
            "online_devices": online_devices,
            "total_users": total_users,
            "connections_today": connections_today,
            "active_sessions": active_sessions,
        }


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
