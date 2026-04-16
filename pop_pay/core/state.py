import sqlite3
import os
from datetime import date, datetime, timezone

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
        # RT-2 R2 N2: owner-only permissions on the DB file. POSIX only;
        # Windows ACLs are intentionally out of scope for this fix.
        if db_path != ":memory:":
            try:
                os.chmod(self.db_path, 0o600)
            except (OSError, NotImplementedError):
                pass
        self._init_db()
        self.daily_spend_total = self._get_today_spent()

    def _init_db(self):
        cursor = self.conn.cursor()
        # RT-2 R2 N1: secure_delete overwrites freed pages during DELETE
        # and VACUUM, so legacy card_number residue in the freelist is
        # zeroed rather than left as readable plaintext.
        cursor.execute("PRAGMA secure_delete = ON")
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
                outcome TEXT,
                rejection_reason TEXT,
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

        # v0.8.2 — audit_log: add outcome + rejection_reason columns if missing.
        # Idempotent: we check PRAGMA before ALTERing. Legacy rows (from v0.8.0/v0.8.1
        # before this column existed) get outcome='unknown' so the dashboard can
        # surface them without breaking. rejection_reason is left NULL for legacy
        # rows since we genuinely have no reason data for them.
        cursor.execute("PRAGMA table_info(audit_log)")
        audit_columns = {row[1] for row in cursor.fetchall()}
        if "outcome" not in audit_columns:
            cursor.execute("ALTER TABLE audit_log ADD COLUMN outcome TEXT")
            cursor.execute("UPDATE audit_log SET outcome = 'unknown' WHERE outcome IS NULL")
        if "rejection_reason" not in audit_columns:
            cursor.execute("ALTER TABLE audit_log ADD COLUMN rejection_reason TEXT")
        self.conn.commit()

        # RT-2 R2 N1: one-time VACUUM to rewrite all pages, including the
        # freelist pages that still hold plaintext card_number data after
        # the legacy DROP TABLE + RENAME. secure_delete (set in _init_db)
        # determines the fill pattern for freed pages. Idempotent via
        # user_version — re-opening an already-migrated DB skips the VACUUM.
        cursor.execute("PRAGMA user_version")
        user_version = cursor.fetchone()[0]
        if user_version < 2:
            cursor.execute("VACUUM")
            cursor.execute("PRAGMA user_version = 2")
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
        # RT-2 R2 Fix 4: masked_card is a PCI-DSS 3.3 permitted last-4
        # projection (already redacted); prior AES-GCM-over-hostname-HMAC
        # added no meaningful protection over the N2 0600 file mode and was
        # undermining auditability. Stored plaintext from v0.8.9 forward.
        timestamp = self._utc_now_iso()
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO issued_seals (seal_id, amount, vendor, status, masked_card, expiration_date, timestamp, rejection_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (seal_id, amount, vendor, status, masked_card, expiration_date, timestamp, rejection_reason))
        self.conn.commit()

    def get_seal_masked_card(self, seal_id: str) -> str:
        """Return the masked card string for a given seal_id (safe to show)."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT masked_card FROM issued_seals WHERE seal_id = ?", (seal_id,))
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]
        return ""

    def update_seal_status(self, seal_id: str, status: str):
        """Update the status of an existing seal."""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE issued_seals SET status = ? WHERE seal_id = ?", (status, seal_id))
        self.conn.commit()

    def record_audit_event(
        self,
        event_type: str,
        vendor: str = None,
        reasoning: str = None,
        outcome: str = None,
        rejection_reason: str = None,
    ) -> int:
        """Insert an audit log entry. Returns the new row id.

        outcome values used by mcp_server.request_purchaser_info:
          - "approved"          — request passed all checks and was fulfilled
          - "rejected_vendor"   — vendor not in allowlist (and blocking enabled)
          - "rejected_security" — security scan blocked the request
          - "blocked_bypassed"  — vendor block bypassed via POP_PURCHASER_INFO_BLOCKING=false
          - "error_injector"    — injector unavailable (CDP down, lazy-init failed)
          - "error_fields"      — billing fields not found on page
          - "unknown"           — legacy row from before v0.8.2 (pre-outcome column)
        """
        timestamp = self._utc_now_iso()
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO audit_log (event_type, vendor, reasoning, outcome, rejection_reason, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (event_type, vendor, reasoning, outcome, rejection_reason, timestamp))
        self.conn.commit()
        return cursor.lastrowid

    def get_audit_events(self, limit: int = 100) -> list[dict]:
        """Return audit log entries, most recent first, as list of dicts with keys
        id, event_type, vendor, reasoning, outcome, rejection_reason, timestamp."""
        try:
            self.conn.row_factory = sqlite3.Row
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id, event_type, vendor, reasoning, outcome, rejection_reason, timestamp "
                "FROM audit_log ORDER BY timestamp DESC, id DESC LIMIT ?",
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
