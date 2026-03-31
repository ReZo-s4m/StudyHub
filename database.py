import sqlite3
import json
import os
from datetime import datetime


DB_NAME = "notes_app.db"


def get_connection():
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database and create tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    # Users table — now only stores local profile data, not auth credentials
    # (auth is handled entirely by Firebase)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid TEXT,
            username TEXT,
            email TEXT,
            full_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Study notes table — per-user storage
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            input_type TEXT DEFAULT 'unknown',
            result_data TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Personal annotations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS personal_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            study_note_id INTEGER,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (study_note_id) REFERENCES study_notes(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()


def get_user_by_firebase_uid(firebase_uid):
    """Look up a local user record by Firebase UID. Returns user dict or None."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, firebase_uid, username, email, full_name, created_at FROM users WHERE firebase_uid = ?",
        (firebase_uid,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "firebase_uid": row["firebase_uid"],
        "username": row["username"],
        "email": row["email"],
        "full_name": row["full_name"],
        "created_at": row["created_at"],
    }


def create_local_user(firebase_uid, email, username="", full_name=""):
    """
    Create a local user record linked to a Firebase UID.
    Called the first time a Firebase user logs in so they have a row
    in the local DB for study notes storage.
    Returns the new user's id.
    """
    conn = get_connection()
    cursor = conn.cursor()
    # Use the Firebase UID as the local username if not provided
    username = username or firebase_uid[:20]
    cursor.execute(
        "INSERT INTO users (firebase_uid, username, email, full_name) VALUES (?, ?, ?, ?)",
        (firebase_uid, username, email, full_name)
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return user_id


def get_or_create_local_user(firebase_uid, email, name=""):
    """
    Get existing local user or create one if they don't have a record yet.
    Returns (user_id, created) tuple.
    """
    existing = get_user_by_firebase_uid(firebase_uid)
    if existing:
        return existing["id"], False
    user_id = create_local_user(firebase_uid, email, full_name=name)
    return user_id, True


# =============================================
# Study Notes — Per-User Storage
# =============================================

def save_study_note(user_id, result_data, input_type="unknown"):
    """Save a generated study note for a user. Returns (success, note_id or error)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Derive a short title from the concept snapshot
        snapshot = result_data.get("concept_snapshot", {})
        title = (snapshot.get("what", "") or "Untitled Note")[:120]
        if len(title) > 100:
            title = title[:100] + "..."

        # Serialise result_data to JSON (strip large fields to save space)
        data_to_store = {k: v for k, v in result_data.items() if k != "output_file"}
        result_json = json.dumps(data_to_store, ensure_ascii=False, default=str)

        cursor.execute(
            "INSERT INTO study_notes (user_id, title, input_type, result_data) VALUES (?, ?, ?, ?)",
            (user_id, title, input_type, result_json)
        )
        note_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return True, note_id
    except Exception as e:
        return False, f"Failed to save note: {str(e)}"


def get_user_notes(user_id, limit=50):
    """Retrieve all study notes for a user, newest first."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, input_type, result_data, created_at FROM study_notes WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        )
        rows = cursor.fetchall()
        conn.close()

        notes = []
        for row in rows:
            try:
                result = json.loads(row["result_data"])
            except json.JSONDecodeError:
                result = {}
            notes.append({
                "id": row["id"],
                "title": row["title"],
                "input_type": row["input_type"],
                "result": result,
                "timestamp": row["created_at"],
            })
        return notes
    except Exception as e:
        print(f"Error loading notes: {e}")
        return []


def delete_study_note(note_id, user_id):
    """Delete a study note (only if it belongs to the user). Returns success bool."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM study_notes WHERE id = ? AND user_id = ?",
            (note_id, user_id)
        )
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted
    except Exception as e:
        print(f"Error deleting note: {e}")
        return False


def get_user_stats(user_id):
    """Get summary statistics for a user."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM study_notes WHERE user_id = ?", (user_id,))
        total = cursor.fetchone()["total"]
        cursor.execute(
            "SELECT created_at FROM study_notes WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        )
        last_row = cursor.fetchone()
        last_activity = last_row["created_at"] if last_row else None
        conn.close()
        return {"total_notes": total, "last_activity": last_activity}
    except Exception as e:
        print(f"Error getting stats: {e}")
        return {"total_notes": 0, "last_activity": None}


# =============================================
# Personal Annotations
# =============================================

def save_personal_note(user_id, text, study_note_id=None):
    """Save a personal annotation."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO personal_notes (user_id, study_note_id, text) VALUES (?, ?, ?)",
            (user_id, study_note_id, text)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving personal note: {e}")
        return False


def get_personal_notes(user_id):
    """Get all personal annotations for a user."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, text, created_at FROM personal_notes WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [{"id": r["id"], "text": r["text"], "time": r["created_at"]} for r in rows]
    except Exception as e:
        print(f"Error loading personal notes: {e}")
        return []


def delete_personal_note(note_id, user_id):
    """Delete a personal annotation."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM personal_notes WHERE id = ? AND user_id = ?", (note_id, user_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error deleting personal note: {e}")
        return False
