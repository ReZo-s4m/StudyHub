import sqlite3
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta


DB_NAME = "notes_app.db"
SESSION_TIMEOUT_HOURS = 24  # Session expires after 24 hours of inactivity


def get_connection():
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database and create tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
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

    # Session tokens table — for persistent login across page refreshes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    # Create index on token for fast lookup
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token)")

    conn.commit()
    conn.close()


def hash_password(password):
    """Hash a password using SHA-256 with a salt."""
    salt = "exam_study_notes_salt_2026"
    return hashlib.sha256((password + salt).encode()).hexdigest()


def register_user(username, email, password, full_name=""):
    """Register a new user. Returns (success, message)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Check if username already exists
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            conn.close()
            return False, "Username already exists. Please choose a different one."
        
        # Check if email already exists
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        if cursor.fetchone():
            conn.close()
            return False, "Email already registered. Please use a different email."
        
        # Insert new user
        password_hash = hash_password(password)
        cursor.execute(
            "INSERT INTO users (username, email, password_hash, full_name) VALUES (?, ?, ?, ?)",
            (username, email, password_hash, full_name)
        )
        conn.commit()
        conn.close()
        return True, "Account created successfully! Please log in."
    
    except Exception as e:
        return False, f"Registration failed: {str(e)}"


def login_user(username, password):
    """Authenticate a user. Returns (success, user_data or error_message)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        password_hash = hash_password(password)
        cursor.execute(
            "SELECT id, username, email, full_name, created_at FROM users WHERE username = ? AND password_hash = ?",
            (username, password_hash)
        )
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return True, {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "full_name": user["full_name"],
                "created_at": user["created_at"]
            }
        else:
            return False, "Invalid username or password."
    
    except Exception as e:
        return False, f"Login failed: {str(e)}"


# =============================================
# Study Notes — Per-User Storage
# =============================================

def save_study_note(user_id, result_data, input_type="unknown"):
    """Save a generated study note for a user. Returns (success, note_id or error)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Derive a short title from the concept snapshot
        snapshot = result_data.get('concept_snapshot', {})
        title = (snapshot.get('what', '') or 'Untitled Note')[:120]
        if len(title) > 100:
            title = title[:100] + "..."

        # Serialise result_data to JSON (strip large fields to save space)
        data_to_store = {k: v for k, v in result_data.items() if k != 'output_file'}
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
                "timestamp": row["created_at"]
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


# =============================================
# Session Management — Persistent Login
# =============================================

def create_session(user_id):
    """Create a new session token for a user. Returns token string."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Generate a secure random token
        token = secrets.token_urlsafe(32)
        
        cursor.execute(
            "INSERT INTO sessions (user_id, token) VALUES (?, ?)",
            (user_id, token)
        )
        conn.commit()
        conn.close()
        return token
    except Exception as e:
        print(f"Error creating session: {e}")
        return None


def validate_session(token):
    """Validate a session token and check if it's still active. Returns (valid, user_data or None)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Get session and check timeout
        cursor.execute(
            """SELECT s.user_id, s.last_accessed, u.id, u.username, u.email, u.full_name, u.created_at 
               FROM sessions s 
               JOIN users u ON s.user_id = u.id 
               WHERE s.token = ?""",
            (token,)
        )
        session = cursor.fetchone()
        
        if not session:
            conn.close()
            return False, None
        
        # Check if session has expired
        last_accessed = datetime.fromisoformat(session["last_accessed"])
        timeout_threshold = datetime.now() - timedelta(hours=SESSION_TIMEOUT_HOURS)
        
        if last_accessed < timeout_threshold:
            # Session expired, delete it
            cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            conn.close()
            return False, None
        
        # Update last_accessed timestamp
        cursor.execute(
            "UPDATE sessions SET last_accessed = CURRENT_TIMESTAMP WHERE token = ?",
            (token,)
        )
        conn.commit()
        conn.close()
        
        # Return valid user data
        user_data = {
            "id": session["id"],
            "username": session["username"],
            "email": session["email"],
            "full_name": session["full_name"],
            "created_at": session["created_at"]
        }
        return True, user_data
    
    except Exception as e:
        print(f"Error validating session: {e}")
        return False, None


def destroy_session(token):
    """Delete a session token (on logout). Returns success bool."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted
    except Exception as e:
        print(f"Error destroying session: {e}")
        return False


def destroy_all_user_sessions(user_id):
    """Delete all sessions for a user (on logout). Returns success bool."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error destroying user sessions: {e}")
        return False
