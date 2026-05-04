import sqlite3
import uuid
from datetime import datetime
from contextlib import contextmanager
from config import Config


class Database:
    def __init__(self):
        self.db_path = Config.DB_PATH
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id     INTEGER PRIMARY KEY,
                    language    TEXT    DEFAULT 'French',
                    created_at  TEXT    DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS video_queue (
                    id              TEXT PRIMARY KEY,
                    chat_id         INTEGER NOT NULL,
                    url             TEXT NOT NULL,
                    status          TEXT DEFAULT 'queued',
                    title           TEXT,
                    language        TEXT,
                    transcript      TEXT,
                    processed_at    TEXT,
                    error           TEXT,
                    created_at      TEXT DEFAULT (datetime('now')),
                    UNIQUE(chat_id, url)
                );

                CREATE TABLE IF NOT EXISTS vocabulary (
                    id              TEXT PRIMARY KEY,
                    chat_id         INTEGER NOT NULL,
                    video_id        TEXT NOT NULL,
                    word            TEXT NOT NULL,
                    phonetic        TEXT,
                    definition_en   TEXT,
                    definition_native TEXT,
                    example         TEXT,
                    sent_at         TEXT,
                    created_at      TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(video_id) REFERENCES video_queue(id)
                );

                CREATE TABLE IF NOT EXISTS known_words (
                    chat_id     INTEGER NOT NULL,
                    word        TEXT NOT NULL,
                    added_at    TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY(chat_id, word)
                );

                CREATE INDEX IF NOT EXISTS idx_vocab_chat ON vocabulary(chat_id);
                CREATE INDEX IF NOT EXISTS idx_queue_status ON video_queue(status);
            """)

    # --- Users ---

    def get_user_language(self, chat_id: int) -> str:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT language FROM users WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            return row["language"] if row else "French"

    def set_user_language(self, chat_id: int, language: str):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO users (chat_id, language) VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET language = excluded.language
            """, (chat_id, language))

    def get_all_chat_ids(self) -> list:
        with self._conn() as conn:
            rows = conn.execute("SELECT DISTINCT chat_id FROM users").fetchall()
            return [r["chat_id"] for r in rows]

    # --- Queue ---

    def enqueue_video(self, chat_id: int, url: str) -> str | None:
        # Ensure user exists
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (chat_id,)
            )
            language = conn.execute(
                "SELECT language FROM users WHERE chat_id = ?", (chat_id,)
            ).fetchone()["language"]

        job_id = str(uuid.uuid4())
        try:
            with self._conn() as conn:
                conn.execute("""
                    INSERT INTO video_queue (id, chat_id, url, language)
                    VALUES (?, ?, ?, ?)
                """, (job_id, chat_id, url, language))
            return job_id
        except sqlite3.IntegrityError:
            return None  # Already queued

    def get_queued_videos(self, limit: int = 5) -> list:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM video_queue
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def update_video_status(self, video_id: str, status: str, **kwargs):
        fields = ["status = ?"]
        values = [status]
        for k, v in kwargs.items():
            fields.append(f"{k} = ?")
            values.append(v)
        if status in ("done", "failed"):
            fields.append("processed_at = ?")
            values.append(datetime.utcnow().isoformat())
        values.append(video_id)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE video_queue SET {', '.join(fields)} WHERE id = ?",
                values
            )

    def get_queue_stats(self, chat_id: int) -> dict:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT status, COUNT(*) as count
                FROM video_queue WHERE chat_id = ?
                GROUP BY status
            """, (chat_id,)).fetchall()
            stats = {"queued": 0, "processing": 0, "done": 0, "failed": 0}
            for r in rows:
                stats[r["status"]] = r["count"]
            return stats

    def get_processed_videos(self, chat_id: int, limit: int = 10) -> list:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT vq.*, COUNT(v.id) as vocab_count
                FROM video_queue vq
                LEFT JOIN vocabulary v ON v.video_id = vq.id
                WHERE vq.chat_id = ? AND vq.status = 'done'
                GROUP BY vq.id
                ORDER BY vq.processed_at DESC
                LIMIT ?
            """, (chat_id, limit)).fetchall()
            return [dict(r) for r in rows]

    # --- Vocabulary ---

    def save_vocabulary(self, chat_id: int, video_id: str, words: list):
        with self._conn() as conn:
            for w in words:
                conn.execute("""
                    INSERT OR IGNORE INTO vocabulary
                    (id, chat_id, video_id, word, phonetic, definition_en, definition_native, example)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(uuid.uuid4()), chat_id, video_id,
                    w.get("word"), w.get("phonetic"),
                    w.get("definition_en"), w.get("definition_native"),
                    w.get("example")
                ))
            # Add words to known words
            for w in words:
                conn.execute(
                    "INSERT OR IGNORE INTO known_words (chat_id, word) VALUES (?, ?)",
                    (chat_id, w["word"].lower())
                )

    def get_known_words(self, chat_id: int) -> set:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT word FROM known_words WHERE chat_id = ?", (chat_id,)
            ).fetchall()
            return {r["word"] for r in rows}

    def get_pending_vocab(self, chat_id: int) -> list:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM vocabulary
                WHERE chat_id = ? AND sent_at IS NULL
                ORDER BY created_at DESC
                LIMIT 30
            """, (chat_id,)).fetchall()
            return [dict(r) for r in rows]

    def mark_vocab_sent(self, chat_id: int):
        with self._conn() as conn:
            conn.execute("""
                UPDATE vocabulary SET sent_at = ?
                WHERE chat_id = ? AND sent_at IS NULL
            """, (datetime.utcnow().isoformat(), chat_id))

    def get_video_vocab(self, video_id: str) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM vocabulary WHERE video_id = ?", (video_id,)
            ).fetchall()
            return [dict(r) for r in rows]
