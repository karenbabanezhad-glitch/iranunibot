import sqlite3
import os
from typing import Optional, List, Dict

DB_PATH = os.environ.get("DB_PATH", "bot_data.db")


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT NOT NULL,
                role        TEXT DEFAULT NULL,
                support_id  INTEGER DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS homeworks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id  INTEGER NOT NULL,
                support_id  INTEGER NOT NULL,
                chat_id     INTEGER NOT NULL,
                message_id  INTEGER NOT NULL,
                caption     TEXT DEFAULT '',
                reply_text  TEXT DEFAULT NULL,
                replied     INTEGER DEFAULT 0,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self.conn.commit()

    # ── Users ──────────────────────────────────────────────────────────────────

    def ensure_user(self, user_id: int, username: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username)
        )
        self.conn.execute(
            "UPDATE users SET username = ? WHERE user_id = ?",
            (username, user_id)
        )
        self.conn.commit()

    def set_role(self, user_id: int, role: str):
        self.conn.execute(
            "UPDATE users SET role = ? WHERE user_id = ?",
            (role, user_id)
        )
        self.conn.commit()

    def get_role(self, user_id: int) -> Optional[str]:
        row = self.conn.execute(
            "SELECT role FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["role"] if row else None

    def get_user(self, user_id: int) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_supports(self) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT * FROM users WHERE role = 'support'"
        ).fetchall()
        return [dict(r) for r in rows]

    def set_student_support(self, student_id: int, support_id: int):
        self.conn.execute(
            "UPDATE users SET support_id = ? WHERE user_id = ?",
            (support_id, student_id)
        )
        self.conn.commit()

    def get_student_support(self, student_id: int) -> Optional[int]:
        row = self.conn.execute(
            "SELECT support_id FROM users WHERE user_id = ?", (student_id,)
        ).fetchone()
        return row["support_id"] if row else None

    # ── Homeworks ──────────────────────────────────────────────────────────────

    def save_homework(self, student_id: int, support_id: int,
                      message_id: int, chat_id: int, caption: str) -> int:
        cur = self.conn.execute(
            """INSERT INTO homeworks (student_id, support_id, chat_id, message_id, caption)
               VALUES (?, ?, ?, ?, ?)""",
            (student_id, support_id, chat_id, message_id, caption)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_homework(self, hw_id: int) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT * FROM homeworks WHERE id = ?", (hw_id,)
        ).fetchone()
        return dict(row) if row else None

    def save_reply(self, hw_id: int, reply_text: str):
        self.conn.execute(
            "UPDATE homeworks SET reply_text = ?, replied = 1 WHERE id = ?",
            (reply_text, hw_id)
        )
        self.conn.commit()

    def get_homeworks_for_support(self, support_id: int) -> List[Dict]:
        rows = self.conn.execute(
            """SELECT h.*, u.username as student_name
               FROM homeworks h
               JOIN users u ON h.student_id = u.user_id
               WHERE h.support_id = ?
               ORDER BY h.created_at DESC
               LIMIT 30""",
            (support_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_homeworks(self) -> List[Dict]:
        rows = self.conn.execute(
            """SELECT h.*,
                      s.username as student_name,
                      sp.username as support_name
               FROM homeworks h
               JOIN users s ON h.student_id = s.user_id
               JOIN users sp ON h.support_id = sp.user_id
               ORDER BY h.created_at DESC
               LIMIT 50"""
        ).fetchall()
        return [dict(r) for r in rows]

    def count_homeworks(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) as c FROM homeworks").fetchone()
        return row["c"]

    def count_replied(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as c FROM homeworks WHERE replied = 1"
        ).fetchone()
        return row["c"]
