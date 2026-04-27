import sqlite3
import os
import sys
import secrets
import contextlib
from datetime import datetime, timezone, timedelta

# Indian Standard Time = UTC+5:30
_IST = timezone(timedelta(hours=5, minutes=30))

def ist_now() -> str:
    """Current time as an IST datetime string (stored in DB and returned to frontend)."""
    return datetime.now(_IST).strftime('%Y-%m-%d %H:%M:%S')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

DB_PATH = os.path.join(os.path.dirname(__file__), "surveillance.db")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with contextlib.closing(get_db_connection()) as conn:
        cursor = conn.cursor()

        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'operator',
                status TEXT DEFAULT 'Active',
                last_active TEXT DEFAULT 'Just now'
            )
        ''')

        # Create alerts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id TEXT,
                event_type TEXT NOT NULL,
                risk_score REAL NOT NULL,
                risk_level TEXT DEFAULT 'low',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                camera_id TEXT,
                location TEXT DEFAULT 'Main Entrance',
                status TEXT DEFAULT 'Active'
            )
        ''')

        # Create incidents table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                event_type TEXT,
                location TEXT DEFAULT 'Main Entrance',
                risk_level TEXT DEFAULT 'low',
                status TEXT DEFAULT 'open',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME,
                clip_path TEXT,
                person_id TEXT,
                camera_id TEXT DEFAULT 'CAM-01'
            )
        ''')

        _ensure_columns(cursor, "incidents", {
            "clip_path": "TEXT",
            "person_id": "TEXT",
            "camera_id": "TEXT DEFAULT 'CAM-01'",
        })

        # Seed default data if tables are empty
        _seed_data(cursor)

        conn.commit()


def _ensure_columns(cursor, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, ddl in columns.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _seed_data(cursor):
    from werkzeug.security import generate_password_hash

    # --- Seed admin user from env vars or generate random password ---
    cursor.execute('SELECT COUNT(*) FROM users')
    if cursor.fetchone()[0] == 0:
        admin_user = os.environ.get("ADMIN_USERNAME", "admin")
        admin_pass = os.environ.get("ADMIN_PASSWORD")

        if not admin_pass:
            admin_pass = secrets.token_urlsafe(12)
            print("[SEED] No ADMIN_PASSWORD env var set.")
            print("[SEED] Generated admin credentials securely.")
            print("[SEED] Note: Ensure you set ADMIN_USERNAME and ADMIN_PASSWORD in production.")

        operator_pass = os.environ.get("OPERATOR_PASSWORD")
        viewer_pass = os.environ.get("VIEWER_PASSWORD")

        if not operator_pass or not viewer_pass:
            print("[SEED] WARNING: Random fallback passwords generated for operator1 and/or viewer1.")
            print("[SEED] WARNING: These are unrecoverable placeholders. Set OPERATOR_PASSWORD and VIEWER_PASSWORD to customize them.")

        operator_pass = operator_pass or secrets.token_urlsafe(12)
        viewer_pass = viewer_pass or secrets.token_urlsafe(12)

        users = [
            (admin_user, generate_password_hash(admin_pass), "admin", "Active", "N/A"),
            ("operator1", generate_password_hash(operator_pass), "security", "Active", "N/A"),
            ("viewer1", generate_password_hash(viewer_pass), "viewer", "Active", "N/A"),
        ]
        cursor.executemany(
            'INSERT INTO users (username, password_hash, role, status, last_active) VALUES (?, ?, ?, ?, ?)',
            users
        )

    # No seed alerts or incidents — the system populates real data from the AI pipeline


def add_alert(person_id, event_type, risk_score, risk_level, camera_id="CAM-01", location="Main Entrance", status="Active"):
    """
    Persists a new alert to the database.
    
    Parameters
    ----------
    person_id : str
        Unique identifier for the detected person.
    event_type : str
        Type of event detected (e.g., "Suspicious Behavior", "Weapon Detected").
    risk_score : float
        Computed risk score (0.0 to 1.0).
    risk_level : str
        Risk level classification ("low", "medium", "high", "critical").
    camera_id : str
        Camera identifier (default "CAM-01").
    location : str
        Location description (default "Main Entrance").
    status : str
        Alert status (default "Active").
    
    Returns
    -------
    int
        The ID of the newly inserted alert.
    
    Raises
    ------
    ValueError
        If required fields are empty or values are out of range.
    """
    # Validate required fields
    if not person_id or not str(person_id).strip():
        raise ValueError("person_id cannot be empty")
    if not event_type or not str(event_type).strip():
        raise ValueError("event_type cannot be empty")
    
    # Validate and clamp risk_score to [0.0, 1.0]
    try:
        risk_score = float(risk_score)
    except (ValueError, TypeError):
        raise ValueError("risk_score must be a number")
    risk_score = max(0.0, min(1.0, risk_score))
    
    # Validate and normalize risk_level
    allowed_risk_levels = {"low", "medium", "high", "critical"}
    risk_level = str(risk_level).strip().lower()
    if risk_level not in allowed_risk_levels:
        raise ValueError(f"risk_level must be one of {allowed_risk_levels}")
    
    # Validate and normalize status
    allowed_statuses = {"active", "resolved", "dismissed"}
    status = str(status).strip().lower().capitalize()  # Normalize: "Active", "Resolved", "Dismissed"
    if status.lower() not in allowed_statuses:
        status = "Active"  # Default to Active for unknown statuses
    
    # Sanitize string fields
    camera_id = str(camera_id).strip() if camera_id else "CAM-01"
    location = str(location).strip() if location else "Main Entrance"
    
    with contextlib.closing(get_db_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO alerts (person_id, event_type, risk_score, risk_level, camera_id, location, status, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (str(person_id).strip(), str(event_type).strip(), risk_score, risk_level,
             camera_id, location, status, ist_now())
        )
        conn.commit()
        return cursor.lastrowid


def add_incident(
    title,
    description,
    event_type,
    location="Main Entrance",
    risk_level="low",
    status="open",
    clip_path=None,
    person_id=None,
    camera_id="CAM-01",
):
    """
    Persists a new incident to the database.
    
    Parameters
    ----------
    title : str
        Short title for the incident.
    description : str
        Detailed description of the incident.
    event_type : str
        Type of event (e.g., "Suspicious Behavior", "Unauthorized Access").
    location : str
        Location description (default "Main Entrance").
    risk_level : str
        Risk level classification ("low", "medium", "high", "critical").
    status : str
        Incident status (default "open").
    
    Returns
    -------
    int
        The ID of the newly inserted incident.
    
    Raises
    ------
    ValueError
        If required fields are empty or values are invalid.
    """
    # Validate required fields
    if not title or not str(title).strip():
        raise ValueError("title cannot be empty")
    if not event_type or not str(event_type).strip():
        raise ValueError("event_type cannot be empty")
    
    # Sanitize description (can be empty but should be string)
    description = str(description).strip() if description else ""
    
    # Validate and normalize risk_level
    allowed_risk_levels = {"low", "medium", "high", "critical"}
    risk_level = str(risk_level).strip().lower()
    if risk_level not in allowed_risk_levels:
        raise ValueError(f"risk_level must be one of {allowed_risk_levels}")
    
    # Validate and normalize status
    allowed_statuses = {"open", "resolved", "escalated", "false alarm"}
    status = str(status).strip().lower()
    if status not in allowed_statuses:
        status = "open"  # Default to open for unknown statuses
    # Capitalize for display consistency
    status = status.title()
    
    # Sanitize location
    location = str(location).strip() if location else "Main Entrance"
    
    with contextlib.closing(get_db_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO incidents
               (title, description, event_type, location, risk_level, status, created_at, clip_path, person_id, camera_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                str(title).strip(),
                description,
                str(event_type).strip(),
                location,
                risk_level,
                status,
                ist_now(),
                str(clip_path) if clip_path else None,
                str(person_id).strip() if person_id is not None else None,
                str(camera_id).strip() if camera_id else "CAM-01",
            )
        )
        conn.commit()
        return cursor.lastrowid


if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")
