import sqlite3
from datetime import date

class PopStateTracker:
    def __init__(self, db_path: str = "pop_state.db"):
        self.db_path = db_path
        # We keep the connection open for the lifetime of the tracker
        # This is especially important for :memory: databases
        self.conn = sqlite3.connect(self.db_path)
        self._init_db()
        self.daily_spend_total = self._get_today_spent()

    def _init_db(self):
        cursor = self.conn.cursor()
        # Create daily_budget table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_budget (
                date TEXT PRIMARY KEY,
                spent_amount FLOAT
            )
        """)
        # Create issued_seals table
        # v0.3.0: Added card_number, cvv, expiration_date for BYOC/Injection
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS issued_seals (
                seal_id TEXT PRIMARY KEY,
                amount FLOAT,
                vendor TEXT,
                status TEXT,
                card_number TEXT,
                cvv TEXT,
                expiration_date TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def _get_today_spent(self) -> float:
        today = date.today().isoformat()
        cursor = self.conn.cursor()
        cursor.execute("SELECT spent_amount FROM daily_budget WHERE date = ?", (today,))
        row = cursor.fetchone()
        return row[0] if row else 0.0

    def can_spend(self, amount: float, max_daily_budget: float) -> bool:
        spent_today = self._get_today_spent()
        return (spent_today + amount) <= max_daily_budget

    def add_spend(self, amount: float):
        today = date.today().isoformat()
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO daily_budget (date, spent_amount) 
            VALUES (?, ?) 
            ON CONFLICT(date) DO UPDATE SET spent_amount = spent_amount + ?
        """, (today, amount, amount))
        self.conn.commit()
        self.daily_spend_total = self._get_today_spent()

    def record_seal(self, seal_id: str, amount: float, vendor: str, status: str = "Issued", card_number: str = None, cvv: str = None, expiration_date: str = None):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO issued_seals (seal_id, amount, vendor, status, card_number, cvv, expiration_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (seal_id, amount, vendor, status, card_number, cvv, expiration_date))
        self.conn.commit()

    def get_seal_details(self, seal_id: str) -> dict:
        """
        Retrieves full card details for a given seal_id. 
        Note: This is intended for local trusted mode (BYOC).
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT card_number, cvv, expiration_date FROM issued_seals WHERE seal_id = ?", (seal_id,))
        row = cursor.fetchone()
        if row:
            return {
                "card_number": row[0],
                "cvv": row[1],
                "expiration_date": row[2]
            }
        return {}

    def mark_used(self, seal_id: str):
        cursor = self.conn.cursor()
        cursor.execute("UPDATE issued_seals SET status = 'Used' WHERE seal_id = ?", (seal_id,))
        self.conn.commit()

    def is_used(self, seal_id: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT status FROM issued_seals WHERE seal_id = ?", (seal_id,))
        row = cursor.fetchone()
        return row is not None and row[0] == "Used"

    def close(self):
        if hasattr(self, 'conn'):
            self.conn.close()
