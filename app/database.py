import sqlite3


class Database:
    def __init__(self, db_path="state.db"):
        self.db = sqlite3.connect(db_path)
        self._init_db()

    def _init_db(self):
        with self.db:
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS sync_state (
                    message_id INTEGER PRIMARY KEY,
                    source_chat_id INTEGER,
                    dest_message_id INTEGER,
                    file_name TEXT,
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS last_processed (
                    chat_id INTEGER PRIMARY KEY,
                    last_message_id INTEGER
                )
            """)

    def get_last_processed_id(self, chat_id):
        cursor = self.db.execute(
            "SELECT last_message_id FROM last_processed WHERE chat_id = ?",
            (chat_id,),
        )
        result = cursor.fetchone()
        return result[0] if result else 0

    def update_last_processed_id(self, chat_id, message_id):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO last_processed (chat_id, last_message_id) VALUES (?, ?)",
                (chat_id, message_id),
            )

    def is_message_synced(self, message_id):
        cursor = self.db.execute(
            "SELECT 1 FROM sync_state WHERE message_id = ?", (message_id,)
        )
        return cursor.fetchone() is not None

    def save_sync_state(
        self, source_msg_id, source_chat_id, dest_msg_id, file_name
    ):
        with self.db:
            self.db.execute(
                "INSERT INTO sync_state (message_id, source_chat_id, dest_message_id, file_name) VALUES (?, ?, ?, ?)",
                (source_msg_id, source_chat_id, dest_msg_id, file_name),
            )

    def __del__(self):
        self.db.close()
