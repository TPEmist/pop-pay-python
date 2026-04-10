import sqlite3
import os
import base64
import hashlib
import hmac
import socket
from datetime import date, datetime, timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".config", "pop-pay", "pop_state.db")

class PopStateTracker:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.db_path = db_path
        # We keep the connection open for the lifetime of the tracker
        # This is especially important for :memory: databases
        self.conn = sqlite3.connect(self.db_path)
        self._init_db()
        self.daily_spend_total = self._get_today_spent()

    def _get_encryption_key(self) -> bytes:
        """Get the encryption key from env or fallback to host-specific HMAC."""
        key_hex = os.environ.get("POP_STATE_ENCRYPTION_KEY")
        if key_hex:
            try:
                return bytes.fromhex(key_hex)
            except ValueError:
                pass
        # Fallback: HMAC-SHA256 of hostname for machine-specific at-rest security
        return hmac.new(b"pop-pay-state-salt", socket.gethostname().encode(), hashlib.sha256).digest()

    def _encrypt_field(self, value: str | None) -> str | None:
        """Encrypt a string field using AES-256-GCM."""
        if value is None:
            return None
        key = self._get_encryption_key()
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, value.encode(), None)
        return base64.b64encode(nonce + ciphertext).decode('utf-8')

    def _decrypt_field(self, encrypted: str | None) -> str | None:
        """Decrypt a string field. Fallbacks to raw value if decryption fails."""
        if encrypted is None:
            return None
        try:
            data = base64.b64decode(encrypted)
            if len(data) < 12:
                return encrypted
            nonce = data[:12]
            ciphertext = data[12:]
            key = self._get_encryption_key()
            aesgcm = AESGCM(key)
            decrypted = aesgcm.decrypt(nonce, ciphertext, None)
            return decrypted.decode('utf-8')
        except Exception:
            return encrypted  # Fallback to raw value (for legacy unencrypted data)

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
                timestamp TEXT NOT NULL,
                rejection_reason TEXT
            )
        """)
        # Create audit_log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                vendor TEXT,
                reasoning TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        self.conn.commit()
        # Migrate existing DB: if old columns exist, migrate and drop them
        self._migrate_schema()

    def _migrate_schema(self):
        """Migrate old schema (card_number, cvv) and apply other updates."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(issued_seals)")
        columns = {row[1] for row in cursor.fetchall()}

        # Preserve and adapt original migration: if legacy columns exist, rebuild the table to the modern schema.
        if "card_number" in columns or "cvv" in columns:
            if "masked_card" not in columns:
                cursor.execute("ALTER TABLE issued_seals ADD COLUMN masked_card TEXT")
            if "card_number" in columns:
                cursor.execute(
                    "UPDATE issued_seals SET masked_card = '****-****-****-' || substr(card_number, -4) "
                    "WHERE masked_card IS NULL AND card_number IS NOT NULL"
                )
            # Recreate table with the full new schema to handle all changes (drop cols, change types)
            cursor.execute("""
                CREATE TABLE issued_seals_new (
                    seal_id TEXT PRIMARY KEY,
                    amount FLOAT,
                    vendor TEXT,
                    status TEXT,
                    masked_card TEXT,
                    expiration_date TEXT,
                    timestamp TEXT NOT NULL,
                    rejection_reason TEXT
                )
            """)
            cursor.execute("""
                INSERT INTO issued_seals_new (seal_id, amount, vendor, status, masked_card, expiration_date, timestamp, rejection_reason)
                SELECT seal_id, amount, vendor, status, masked_card, expiration_date, COALESCE(timestamp, '1970-01-01T00:00:00Z'), NULL
                FROM issued_seals
            """)
            cursor.execute("DROP TABLE issued_seals")
            cursor.execute("ALTER TABLE issued_seals_new RENAME TO issued_seals")
            self.conn.commit()
            # After rebuild, schema is modern. Re-fetch columns.
            cursor.execute("PRAGMA table_info(issued_seals)")
            columns = {row[1] for row in cursor.fetchall()}

        # ADD: If rejection_reason column is missing (for users not hitting the legacy path)
        if "rejection_reason" not in columns:
            cursor.execute("ALTER TABLE issued_seals ADD COLUMN rejection_reason TEXT")
            self.conn.commit()

        # ADD: One-time UPDATE to convert timestamp format to ISO 8601 with Z.
        # This is safe for all schemas, including freshly migrated ones.
        cursor.execute(
            "UPDATE issued_seals SET timestamp = REPLACE(timestamp, ' ', 'T') || 'Z' "
            "WHERE timestamp NOT LIKE '%T%' AND timestamp IS NOT NULL AND timestamp != ''"
        )
        self.conn.commit()

    def _utc_now_iso(self) -> str:
        """Return the current UTC time as an ISO 8601 string with a Z suffix."""
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

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

    def record_seal(
        self,
        seal_id: str,
        amount: float,
        vendor: str,
        status: str = "Issued",
        masked_card: str = None,
        expiration_date: str = None,
        rejection_reason: str = None,
    ):
        encrypted_card = self._encrypt_field(masked_card)
        timestamp = self._utc_now_iso()
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO issued_seals (seal_id, amount, vendor, status, masked_card, expiration_date, timestamp, rejection_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (seal_id, amount, vendor, status, encrypted_card, expiration_date, timestamp, rejection_reason))
        self.conn.commit()

    def get_seal_masked_card(self, seal_id: str) -> str:
        """Return the masked card string for a given seal_id (safe to show)."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT masked_card FROM issued_seals WHERE seal_id = ?", (seal_id,))
        row = cursor.fetchone()
        if row and row[0]:
            return self._decrypt_field(row[0])
        return ""

    def update_seal_status(self, seal_id: str, status: str):
        """Update the status of an existing seal."""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE issued_seals SET status = ? WHERE seal_id = ?", (status, seal_id))
        self.conn.commit()

    def record_audit_event(self, event_type: str, vendor: str = None, reasoning: str = None) -> int:
        """Insert an audit log entry. Returns the new row id."""
        timestamp = self._utc_now_iso()
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO audit_log (event_type, vendor, reasoning, timestamp)
            VALUES (?, ?, ?, ?)
        """, (event_type, vendor, reasoning, timestamp))
        self.conn.commit()
        return cursor.lastrowid

    def get_audit_events(self, limit: int = 100) -> list[dict]:
        """Return audit log entries, most recent first, as list of dicts with keys
        id, event_type, vendor, reasoning, timestamp."""
        try:
            self.conn.row_factory = sqlite3.Row
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id, event_type, vendor, reasoning, timestamp FROM audit_log ORDER BY timestamp DESC, id DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            self.conn.row_factory = None

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
