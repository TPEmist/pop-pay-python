"""
RT-2 R2 — SecretStr regression tests (Fix 3).

These tests lock in the opaque-wrapper contract for the new
`SecretStr` dataclass. They would FAIL against the previous
`_SecretStr(str)` subclass (which leaked plaintext through
`.encode()`, `str.__add__`, `json.dumps`, `pickle.dumps`, slicing)
and PASS against the new `@dataclass(frozen=True, slots=True)`
implementation.

Audit doc: workspace/projects/pop-pay/rt2-r2/fix3-callsite-audit.md
"""
from __future__ import annotations

import json
import pickle

import pytest

from pop_pay.core.secret_str import SecretStr


# ---------------------------------------------------------------------------
# Masking surface (public-facing stringification)
# ---------------------------------------------------------------------------

def test_str_masked():
    """str(s) returns the opaque marker, never the plaintext."""
    s = SecretStr("4242424242424242")
    assert str(s) == "***REDACTED***"


def test_repr_masked():
    """repr(s) returns a non-leaky representation."""
    s = SecretStr("4242424242424242")
    rep = repr(s)
    assert "4242" not in rep
    assert "REDACTED" in rep


def test_format_masked():
    """f-string interpolation uses __format__, must mask."""
    s = SecretStr("4242424242424242")
    assert f"{s}" == "***REDACTED***"


def test_format_spec_masked():
    """f-string with a format spec (e.g. alignment) must still mask.

    Extra regression test: __format__ must ignore the spec so a sneaky
    alignment directive cannot accidentally reveal the underlying str.
    """
    s = SecretStr("4242424242424242")
    assert f"{s:>20}" == "***REDACTED***"
    assert f"{s:<5}" == "***REDACTED***"


# ---------------------------------------------------------------------------
# Leak vectors that BYPASSED the old str-subclass __str__ / __repr__
# ---------------------------------------------------------------------------

def test_json_dumps_raises():
    """json.dumps must not serialize the plaintext.

    Old _SecretStr(str): json.dumps emitted the full PAN as a JSON string.
    New dataclass: json.dumps raises TypeError since dataclass is not a
    JSON-native type.
    """
    s = SecretStr("4242424242424242")
    with pytest.raises(TypeError):
        json.dumps(s)


def test_str_concat_left_fails():
    """SecretStr + str must raise (no inheriting str.__add__)."""
    s = SecretStr("4242424242424242")
    with pytest.raises(TypeError):
        _ = s + "suffix"


def test_str_concat_right_fails():
    """str + SecretStr must raise."""
    s = SecretStr("4242424242424242")
    with pytest.raises(TypeError):
        _ = "prefix" + s


def test_encode_raises_attributeerror():
    """.encode() must raise — old _SecretStr(str).encode() returned
    plaintext bytes, which was the primary leak vector flagged by RT-2."""
    s = SecretStr("4242424242424242")
    with pytest.raises(AttributeError):
        s.encode("utf-8")


def test_pickle_roundtrip_preserves_type():
    """pickle round-trip must yield a SecretStr, not a bare str.

    Rationale: if pickle returned a str, the plaintext would be visible
    through any downstream logging path that relied on type-dispatch.
    """
    s = SecretStr("4242424242424242")
    data = pickle.dumps(s)
    restored = pickle.loads(data)
    assert isinstance(restored, SecretStr)
    assert restored.reveal() == "4242424242424242"


def test_not_str_subclass():
    """SecretStr must NOT inherit from str.

    If it did, string operations at the C level would continue to leak
    plaintext. This guards against regression.
    """
    s = SecretStr("4242424242424242")
    assert not isinstance(s, str)


# ---------------------------------------------------------------------------
# Explicit plaintext access via .reveal() / .last4()
# ---------------------------------------------------------------------------

def test_reveal_returns_plaintext():
    """Every .reveal() call site must be justifiable; this is the only
    sanctioned way to obtain the underlying string."""
    s = SecretStr("4242424242424242")
    assert s.reveal() == "4242424242424242"


def test_last4_returns_last_four_digits():
    """PCI-DSS 3.3 permitted projection — safe to log / persist."""
    s = SecretStr("4242424242424242")
    assert s.last4() == "4242"


def test_last4_empty_returns_empty_string():
    """Empty SecretStr returns empty last4 (not IndexError)."""
    s = SecretStr("")
    assert s.last4() == ""


def test_last4_short_string_returns_all():
    """Last4 of a short string returns the whole string (Python slice semantics)."""
    s = SecretStr("12")
    assert s.last4() == "12"


# ---------------------------------------------------------------------------
# Immutability / boolean behavior
# ---------------------------------------------------------------------------

def test_frozen_forbids_mutation():
    """frozen=True — attribute reassignment must fail."""
    from dataclasses import FrozenInstanceError
    s = SecretStr("4242424242424242")
    with pytest.raises(FrozenInstanceError):
        s._value = "other"  # type: ignore[misc]


def test_bool_truthy_for_nonempty():
    """bool(SecretStr("x")) is True — enables `if secret:` patterns."""
    assert bool(SecretStr("x")) is True


def test_bool_falsey_for_empty():
    """bool(SecretStr("")) is False — enables empty-sentinel patterns
    used in mcp_server.request_purchaser_info and tools/langchain."""
    assert bool(SecretStr("")) is False


def test_equality_by_value():
    """Two SecretStr with the same plaintext are equal (dataclass default)."""
    assert SecretStr("x") == SecretStr("x")
    assert SecretStr("x") != SecretStr("y")


def test_hashable():
    """frozen=True makes the instance hashable — useful for set/dict keys
    in tests, and for dedup downstream."""
    s1 = SecretStr("x")
    s2 = SecretStr("x")
    assert hash(s1) == hash(s2)
    _ = {s1, s2}  # should not raise


# ---------------------------------------------------------------------------
# Slicing (str subclass leak vector that must NOT work)
# ---------------------------------------------------------------------------

def test_slice_not_supported():
    """SecretStr is not subscriptable — slicing leaked plaintext on
    _SecretStr(str) because slices drop the subclass and return bare str.
    On the dataclass this raises TypeError, forcing use of .last4()."""
    s = SecretStr("4242424242424242")
    with pytest.raises(TypeError):
        _ = s[0:4]
    with pytest.raises(TypeError):
        _ = s[-4:]
