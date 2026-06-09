"""
Database manager for SQLite user base.
Handles schema initialization, hashing password, user details, and sessions.
"""

import os
import sqlite3
import hashlib
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger

DB_PATH = Path(__file__).parent.parent.parent / "db" / "users.db"

def get_db_connection() -> sqlite3.Connection:
    """Returns a connection to the SQLite database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database schema if tables do not exist."""
    logger.info(f"Initializing database at {DB_PATH}")
    with get_db_connection() as conn:
        # Users Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                couple_name TEXT,
                event_date TEXT,
                guest_count TEXT,
                budget TEXT,
                notes TEXT,
                venue_statuses TEXT,
                contacted_venues TEXT,
                activity_feed TEXT
            )
        """)
        # Sessions Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                FOREIGN KEY(email) REFERENCES users(email) ON DELETE CASCADE
            )
        """)
        conn.commit()

def hash_password(password: str) -> str:
    """Hashes a password using PBKDF2-HMAC-SHA256 with a random salt."""
    salt = os.urandom(16)
    pw_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt.hex() + ":" + pw_hash.hex()

def verify_password(password: str, stored_hash: str) -> bool:
    """Verifies a password against a stored PBKDF2 hash."""
    try:
        salt_hex, hash_hex = stored_hash.split(":")
        salt = bytes.fromhex(salt_hex)
        pw_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return pw_hash.hex() == hash_hex
    except Exception as e:
        logger.error(f"Password verification failed: {e}")
        return False

def create_user(email: str, name: str, password: str) -> bool:
    """Creates a new user in the database."""
    try:
        pw_hash = hash_password(password)
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO users (email, name, password_hash) VALUES (?, ?, ?)",
                (email.strip().lower(), name.strip(), pw_hash)
            )
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"User registration failed: email {email} already registered.")
        return False
    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        return False

def get_user_by_email(email: str) -> dict | None:
    """Retrieves a user profile by email."""
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
            if row:
                return dict(row)
    except Exception as e:
        logger.error(f"Error fetching user: {e}")
    return None

def create_session(email: str) -> str:
    """Generates a session token for the user, expiring in 30 days."""
    token = str(uuid.uuid4())
    expires_at = (datetime.now() + timedelta(days=30)).isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (token, email, expires_at) VALUES (?, ?, ?)",
            (token, email.strip().lower(), expires_at)
        )
        conn.commit()
    return token

def get_session_user(token: str) -> dict | None:
    """Validates token and returns the corresponding user profile."""
    try:
        now = datetime.now().isoformat()
        with get_db_connection() as conn:
            row = conn.execute("""
                SELECT users.* FROM sessions
                JOIN users ON sessions.email = users.email
                WHERE sessions.token = ? AND sessions.expires_at > ?
            """, (token, now)).fetchone()
            if row:
                return dict(row)
    except Exception as e:
        logger.error(f"Error validating session token: {e}")
    return None

def delete_session(token: str):
    """Deletes a session token (logout)."""
    with get_db_connection() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()

def sync_user_data(email: str, data: dict) -> bool:
    """Synchronizes user wedding project, venue statuses, contacted timestamps, and activity feed."""
    try:
        with get_db_connection() as conn:
            conn.execute("""
                UPDATE users SET
                    couple_name = ?,
                    event_date = ?,
                    guest_count = ?,
                    budget = ?,
                    notes = ?,
                    venue_statuses = ?,
                    contacted_venues = ?,
                    activity_feed = ?
                WHERE email = ?
            """, (
                data.get("couple_name"),
                data.get("event_date"),
                data.get("guest_count"),
                data.get("budget"),
                data.get("notes"),
                data.get("venue_statuses"),
                data.get("contacted_venues"),
                data.get("activity_feed"),
                email.strip().lower()
            ))
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error synchronizing user data for {email}: {e}")
        return False
