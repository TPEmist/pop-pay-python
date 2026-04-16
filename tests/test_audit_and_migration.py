"""Tests for the v0.8.0 dashboard audit overhaul.

Covers:
- ISO 8601 UTC timestamp format (Bug 1)
- rejection_reason persistence (Bug 2)
- daily_budget update path + dashboard DB path consistency (Bug 3)
- audit_log table + record_audit_event / get_audit_events
- Schema migration from legacy DBs (upgrade safety)
"""
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone

import pytest

from pop_pay.core.state import PopStateTracker, DEFAULT_DB_PATH

ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


# ---------------------------------------------------------------------------
# Bug 1: ISO 8601 timestamps
# ---------------------------------------------------------------------------

def test_record_seal_writes_iso_8601_with_z():
    t = PopStateTracker(":memory:")
    t.record_seal("s1", 10.0, "aws", status="Issued")
    row = t.conn.execute("SELECT timestamp FROM issued_seals WHERE seal_id = ?", ("s1",)).fetchone()
    assert row is not None
    assert ISO_Z_RE.match(row[0]), f"timestamp {row[0]!r} is not ISO 8601 with Z"
    t.close()


def test_audit_event_writes_iso_8601_with_z():
    t = PopStateTracker(":memory:")
    t.record_audit_event("purchaser_info_requested", vendor="aws", reasoning="test")
    events = t.get_audit_events()
    assert len(events) == 1
    assert ISO_Z_RE.match(events[0]["timestamp"]), f"audit timestamp {events[0]['timestamp']!r} invalid"
    t.close()


# ---------------------------------------------------------------------------
# Bug 2: rejection_reason
# ---------------------------------------------------------------------------

def test_record_seal_persists_rejection_reason():
    t = PopStateTracker(":memory:")
    t.record_seal("r1", 0.0, "aws", status="Rejected", rejection_reason="daily budget exceeded")
    row = t.conn.execute("SELECT status, rejection_reason FROM issued_seals WHERE seal_id = ?", ("r1",)).fetchone()
    assert row == ("Rejected", "daily budget exceeded")
    t.close()


def test_record_seal_rejection_reason_optional_defaults_null():
    t = PopStateTracker(":memory:")
    t.record_seal("s1", 10.0, "aws", status="Issued")
    row = t.conn.execute("SELECT rejection_reason FROM issued_seals WHERE seal_id = ?", ("s1",)).fetchone()
    assert row[0] is None
    t.close()


# ---------------------------------------------------------------------------
# Bug 3: dashboard/client db path consistency + addSpend path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_client_addspend_updates_same_db_dashboard_reads():
    """Regression test for npm Bug 3 equivalent: ensure the client writes
    to the same DB path that the dashboard reads."""
    from pop_pay.client import PopClient
    from pop_pay.core.models import GuardrailPolicy, PaymentIntent
    from pop_pay.providers.stripe_mock import MockStripeProvider

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "pop_state.db")
        policy = GuardrailPolicy(
            allowed_categories=["aws"],
            max_amount_per_tx=100,
            max_daily_budget=500,
            block_hallucination_loops=True,
        )
        client = PopClient(MockStripeProvider(), policy, db_path=db_path)
        intent = PaymentIntent(
            agent_id="test",
            requested_amount=25.0,
            target_vendor="aws",
            reasoning="test",
            page_url=None,
        )
        await client.process_payment(intent)

        # Verify daily_budget was updated in the same file the dashboard would read
        conn = sqlite3.connect(db_path)
        from datetime import date
        today = date.today().isoformat()
        row = conn.execute("SELECT spent_amount FROM daily_budget WHERE date = ?", (today,)).fetchone()
        conn.close()
        assert row is not None, "daily_budget row missing — addSpend did not fire"
        assert row[0] == 25.0
        client.state_tracker.close()


# ---------------------------------------------------------------------------
# audit_log functionality
# ---------------------------------------------------------------------------

def test_audit_log_table_created_on_init():
    t = PopStateTracker(":memory:")
    cols = t.conn.execute("PRAGMA table_info(audit_log)").fetchall()
    names = {c[1] for c in cols}
    assert names == {"id", "event_type", "vendor", "reasoning", "outcome", "rejection_reason", "timestamp"}
    t.close()


def test_record_audit_event_returns_rowid():
    t = PopStateTracker(":memory:")
    rid1 = t.record_audit_event("purchaser_info_requested", vendor="aws")
    rid2 = t.record_audit_event("purchaser_info_requested", vendor="github")
    assert rid1 == 1
    assert rid2 == 2
    t.close()


def test_get_audit_events_ordered_desc():
    t = PopStateTracker(":memory:")
    t.record_audit_event("purchaser_info_requested", vendor="a", reasoning="first")
    t.record_audit_event("purchaser_info_requested", vendor="b", reasoning="second")
    t.record_audit_event("purchaser_info_requested", vendor="c", reasoning="third")
    events = t.get_audit_events()
    assert len(events) == 3
    # Most recent first (by id since timestamps may collide at second precision)
    assert [e["reasoning"] for e in events] == ["third", "second", "first"]
    t.close()


def test_get_audit_events_respects_limit():
    t = PopStateTracker(":memory:")
    for i in range(5):
        t.record_audit_event("purchaser_info_requested", vendor=f"v{i}")
    events = t.get_audit_events(limit=2)
    assert len(events) == 2
    t.close()


# ---------------------------------------------------------------------------
# v0.8.2 — audit_log outcome + rejection_reason
# ---------------------------------------------------------------------------

def test_record_audit_event_persists_outcome_and_reason():
    t = PopStateTracker(":memory:")
    t.record_audit_event(
        "purchaser_info_requested",
        vendor="aws",
        reasoning="buying compute",
        outcome="approved",
    )
    t.record_audit_event(
        "purchaser_info_requested",
        vendor="shady.example.com",
        reasoning="n/a",
        outcome="rejected_vendor",
        rejection_reason="vendor 'shady.example.com' not in POP_ALLOWED_CATEGORIES",
    )
    events = t.get_audit_events()
    assert len(events) == 2
    # Most recent first
    assert events[0]["outcome"] == "rejected_vendor"
    assert events[0]["rejection_reason"] == "vendor 'shady.example.com' not in POP_ALLOWED_CATEGORIES"
    assert events[1]["outcome"] == "approved"
    assert events[1]["rejection_reason"] is None
    t.close()


def test_legacy_audit_log_migration_adds_outcome_and_rejection_reason_columns():
    """v0.8.0/v0.8.1 DBs have audit_log without outcome/rejection_reason columns.
    Opening such a DB with v0.8.2 must add the columns and default legacy rows
    to outcome='unknown'."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "legacy_audit.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE audit_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_type TEXT NOT NULL, "
            "vendor TEXT, "
            "reasoning TEXT, "
            "timestamp TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO audit_log (event_type, vendor, reasoning, timestamp) "
            "VALUES (?, ?, ?, ?)",
            ("purchaser_info_requested", "aws", "legacy row", "2026-04-01T12:00:00Z"),
        )
        conn.commit()
        conn.close()

        t = PopStateTracker(db_path)
        cols = {r[1] for r in t.conn.execute("PRAGMA table_info(audit_log)").fetchall()}
        assert "outcome" in cols
        assert "rejection_reason" in cols

        events = t.get_audit_events()
        assert len(events) == 1
        assert events[0]["vendor"] == "aws"
        assert events[0]["outcome"] == "unknown"
        assert events[0]["rejection_reason"] is None
        t.close()


def test_audit_log_migration_idempotent():
    """Running migration twice must not double-apply or clobber data."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "legacy_audit.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE audit_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_type TEXT NOT NULL, "
            "vendor TEXT, "
            "reasoning TEXT, "
            "timestamp TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO audit_log (event_type, vendor, reasoning, timestamp) "
            "VALUES (?, ?, ?, ?)",
            ("purchaser_info_requested", "aws", "legacy", "2026-04-01T12:00:00Z"),
        )
        conn.commit()
        conn.close()

        t1 = PopStateTracker(db_path)
        # Write a new row with an outcome AFTER migration
        t1.record_audit_event(
            "purchaser_info_requested",
            vendor="github",
            outcome="approved",
        )
        t1.close()

        # Second open — migration should be a no-op; existing data preserved.
        t2 = PopStateTracker(db_path)
        events = t2.get_audit_events()
        assert len(events) == 2
        outcomes = {e["vendor"]: e["outcome"] for e in events}
        assert outcomes == {"aws": "unknown", "github": "approved"}
        # Column list still exactly the expected set
        cols = {r[1] for r in t2.conn.execute("PRAGMA table_info(audit_log)").fetchall()}
        assert cols == {"id", "event_type", "vendor", "reasoning", "outcome", "rejection_reason", "timestamp"}
        t2.close()


# ---------------------------------------------------------------------------
# Schema migration from legacy DBs
# ---------------------------------------------------------------------------

def _make_legacy_db(tmp: str, *, with_card_number: bool) -> str:
    """Create a DB with the pre-v0.8.0 schema."""
    db_path = os.path.join(tmp, "legacy.db")
    conn = sqlite3.connect(db_path)
    if with_card_number:
        conn.execute(
            "CREATE TABLE issued_seals ("
            "seal_id TEXT PRIMARY KEY, amount FLOAT, vendor TEXT, status TEXT, "
            "card_number TEXT, cvv TEXT, expiration_date TEXT, "
            "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO issued_seals (seal_id, amount, vendor, status, card_number, cvv, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("vlegacy-1", 99.0, "stripe", "Issued", "4111111111111111", "123", "2026-03-15 10:00:00"),
        )
    else:
        conn.execute(
            "CREATE TABLE issued_seals ("
            "seal_id TEXT PRIMARY KEY, amount FLOAT, vendor TEXT, status TEXT, "
            "masked_card TEXT, expiration_date TEXT, "
            "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO issued_seals (seal_id, amount, vendor, status, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("legacy-1", 50.0, "aws", "Issued", "2026-04-01 12:00:00"),
        )
    conn.commit()
    conn.close()
    return db_path


def test_migration_adds_rejection_reason_column():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _make_legacy_db(tmp, with_card_number=False)
        t = PopStateTracker(db_path)
        cols = [r[1] for r in t.conn.execute("PRAGMA table_info(issued_seals)").fetchall()]
        assert "rejection_reason" in cols
        t.close()


def test_migration_converts_timestamp_to_iso_format():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _make_legacy_db(tmp, with_card_number=False)
        t = PopStateTracker(db_path)
        row = t.conn.execute("SELECT timestamp FROM issued_seals WHERE seal_id = ?", ("legacy-1",)).fetchone()
        assert ISO_Z_RE.match(row[0]), f"{row[0]!r} not migrated to ISO 8601"
        assert row[0] == "2026-04-01T12:00:00Z"
        t.close()


def test_migration_creates_audit_log_for_legacy_db():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _make_legacy_db(tmp, with_card_number=False)
        t = PopStateTracker(db_path)
        # audit_log table must exist and be queryable
        count = t.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        assert count == 0
        t.record_audit_event("purchaser_info_requested", vendor="test")
        count = t.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        assert count == 1
        t.close()


def test_very_legacy_migration_preserves_masked_card():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _make_legacy_db(tmp, with_card_number=True)
        t = PopStateTracker(db_path)
        cols = [r[1] for r in t.conn.execute("PRAGMA table_info(issued_seals)").fetchall()]
        assert "card_number" not in cols
        assert "cvv" not in cols
        assert "rejection_reason" in cols
        row = t.conn.execute("SELECT masked_card, timestamp FROM issued_seals WHERE seal_id = ?", ("vlegacy-1",)).fetchone()
        assert row[0] == "****-****-****-1111"
        assert ISO_Z_RE.match(row[1])
        t.close()


def test_migration_is_idempotent():
    """Running migration twice must not corrupt data."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _make_legacy_db(tmp, with_card_number=False)
        t1 = PopStateTracker(db_path)
        row1 = t1.conn.execute("SELECT timestamp FROM issued_seals WHERE seal_id = ?", ("legacy-1",)).fetchone()
        t1.close()
        t2 = PopStateTracker(db_path)
        row2 = t2.conn.execute("SELECT timestamp FROM issued_seals WHERE seal_id = ?", ("legacy-1",)).fetchone()
        assert row1 == row2
        # Should still be the single-Z format, not doubled
        assert row2[0].count("Z") == 1
        t2.close()


# ---------------------------------------------------------------------------
# RT-2 R2 N1 — VACUUM + secure_delete cleanup of legacy card_number residue
# ---------------------------------------------------------------------------

def test_secure_delete_enabled_on_fresh_db():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "fresh.db")
        t = PopStateTracker(db_path)
        assert t.conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
        t.close()


def test_user_version_bumped_to_2_on_fresh_db():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "fresh.db")
        t = PopStateTracker(db_path)
        assert t.conn.execute("PRAGMA user_version").fetchone()[0] == 2
        t.close()


def test_legacy_migration_scrubs_card_number_from_freelist():
    """RT-2 R2 N1: opening a legacy DB must VACUUM away plaintext card_number
    residue left in freelist pages after the DROP + RENAME rebuild."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "legacy_pan.db")
        # Build a legacy DB with recognizable plaintext PANs we can grep for
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE issued_seals ("
            "seal_id TEXT PRIMARY KEY, amount FLOAT, vendor TEXT, status TEXT, "
            "card_number TEXT, cvv TEXT, expiration_date TEXT, "
            "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        pans = ["4111111111111111", "5555555555554444", "378282246310005"]
        for i, pan in enumerate(pans):
            conn.execute(
                "INSERT INTO issued_seals (seal_id, amount, vendor, status, card_number, cvv, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"v{i}", 10.0, "test", "Issued", pan, "123", "2026-03-15 10:00:00"),
            )
        conn.commit()
        conn.close()

        # Pre-check: raw bytes contain each PAN (proves the test setup
        # actually reproduces the leak before we attempt the fix).
        with open(db_path, "rb") as fh:
            raw = fh.read()
        for pan in pans:
            assert pan.encode() in raw, f"setup sanity: {pan} not in pre-migration DB"

        # Run the new migration.
        t = PopStateTracker(db_path)
        t.close()

        # Post-check: no PAN substring survives the VACUUM.
        with open(db_path, "rb") as fh:
            raw = fh.read()
        for pan in pans:
            assert pan.encode() not in raw, f"PAN {pan} survived VACUUM — freelist leak"


def test_legacy_migration_preserves_masked_rows_through_vacuum():
    """Sibling of the freelist-scrub test: after VACUUM, the migrated rows
    must still be retrievable with their derived masked_card intact."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _make_legacy_db(tmp, with_card_number=True)
        t = PopStateTracker(db_path)
        row = t.conn.execute(
            "SELECT masked_card FROM issued_seals WHERE seal_id = ?", ("vlegacy-1",)
        ).fetchone()
        assert row[0] == "****-****-****-1111"
        t.close()


def test_reopen_does_not_revacuum_when_user_version_already_2():
    """Idempotency: once user_version=2, re-opening must skip the VACUUM
    branch. We prove this by toggling user_version manually to 2 on an
    untouched DB and asserting the migration does not downgrade or rerun."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _make_legacy_db(tmp, with_card_number=False)
        # First open — runs migration, bumps to user_version=2.
        t1 = PopStateTracker(db_path)
        assert t1.conn.execute("PRAGMA user_version").fetchone()[0] == 2
        t1.close()
        # Second open — should NOT re-VACUUM (we cannot directly detect
        # re-VACUUM but we can assert user_version stays 2 and data intact).
        t2 = PopStateTracker(db_path)
        assert t2.conn.execute("PRAGMA user_version").fetchone()[0] == 2
        row = t2.conn.execute(
            "SELECT seal_id FROM issued_seals WHERE seal_id = ?", ("legacy-1",)
        ).fetchone()
        assert row is not None
        t2.close()


# ---------------------------------------------------------------------------
# RT-2 R2 N2 — chmod 0600 state db
# ---------------------------------------------------------------------------

def test_state_db_file_mode_is_0600_on_posix():
    """POSIX-only enforcement: state DB created 0600 (owner r/w only).
    Windows no-op is accepted — test skips there."""
    import platform
    if platform.system() == "Windows":
        pytest.skip("POSIX-only enforcement; Windows ACLs out of scope")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "mode.db")
        t = PopStateTracker(db_path)
        mode = os.stat(db_path).st_mode & 0o777
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"
        t.close()


def test_state_db_mode_reapplied_on_reopen():
    """If the file mode is widened externally (e.g. via `chmod 644`), a
    subsequent open of PopStateTracker must restore 0600."""
    import platform
    if platform.system() == "Windows":
        pytest.skip("POSIX-only enforcement; Windows ACLs out of scope")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "mode_reapply.db")
        t1 = PopStateTracker(db_path)
        t1.close()
        os.chmod(db_path, 0o644)
        assert os.stat(db_path).st_mode & 0o777 == 0o644
        t2 = PopStateTracker(db_path)
        assert os.stat(db_path).st_mode & 0o777 == 0o600
        t2.close()

