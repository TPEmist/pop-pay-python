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
        # Create issued_seals table — security: only masked_card stored, never cvv
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS issued_seals (
                seal_id TEXT PRIMARY KEY,
                amount FLOAT,
                vendor TEXT,
                status TEXT,
                masked_card TEXT,
                expiration_date TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()
        # Migrate existing DB: if old columns exist, migrate and drop them
        self._migrate_schema()

    def _migrate_schema(self):
        """Migrate old schema (card_number, cvv) to new schema (masked_card only)."""
        cursor = self.conn.cursor()
        # Check if old card_number column exists
        cursor.execute("PRAGMA table_info(issued_seals)")
        columns = {row[1] for row in cursor.fetchall()}

        if "card_number" in columns or "cvv" in columns:
            # Add masked_card column if not already present
            if "masked_card" not in columns:
                cursor.execute("ALTER TABLE issued_seals ADD COLUMN masked_card TEXT")
            # Derive masked_card from last 4 digits of card_number
            if "card_number" in columns:
                cursor.execute(
                    "UPDATE issued_seals SET masked_card = '****-****-****-' || substr(card_number, -4) "
                    "WHERE masked_card IS NULL AND card_number IS NOT NULL"
                )
            # Recreate table without card_number and cvv columns (SQLite cannot DROP COLUMN pre-3.35)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS issued_seals_new (
                    seal_id TEXT PRIMARY KEY,
                    amount FLOAT,
                    vendor TEXT,
                    status TEXT,
                    masked_card TEXT,
                    expiration_date TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                INSERT INTO issued_seals_new (seal_id, amount, vendor, status, masked_card, expiration_date, timestamp)
                SELECT seal_id, amount, vendor, status, masked_card, expiration_date, timestamp
                FROM issued_seals
            """)
            cursor.execute("DROP TABLE issued_seals")
            cursor.execute("ALTER TABLE issued_seals_new RENAME TO issued_seals")
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

    def record_seal(self, seal_id: str, amount: float, vendor: str, status: str = "Issued", masked_card: str = None, expiration_date: str = None):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO issued_seals (seal_id, amount, vendor, status, masked_card, expiration_date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (seal_id, amount, vendor, status, masked_card, expiration_date))
        self.conn.commit()

    def get_seal_masked_card(self, seal_id: str) -> str:
        """Return the masked card string for a given seal_id (safe to show)."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT masked_card FROM issued_seals WHERE seal_id = ?", (seal_id,))
        row = cursor.fetchone()
        return row[0] if row else ""

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
