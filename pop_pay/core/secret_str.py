from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SecretStr:
    """Opaque secret-bearing wrapper.

    Unlike the previous `_SecretStr(str)` subclass, this is NOT a `str`
    subclass. String operations (`.encode()`, concat, slicing, `json.dumps`,
    `pickle.dumps` producing a bare string) do NOT transparently leak the
    underlying value. Plaintext access requires an explicit `.reveal()`
    call, making every leak site greppable.

    RT-2 R2 Fix 3 — see workspace/projects/pop-pay/rt2-r2/fix3-callsite-audit.md
    """

    _value: str

    def reveal(self) -> str:
        """Return the plaintext. Every call site must be justifiable —
        the presence of `.reveal()` in the source is the audit footprint."""
        return self._value

    def last4(self) -> str:
        """PCI-DSS 3.3 permitted last-4 projection — safe to log / persist."""
        return self._value[-4:] if self._value else ""

    def __str__(self) -> str:
        return "***REDACTED***"

    def __repr__(self) -> str:
        return "SecretStr('***REDACTED***')"

    def __format__(self, spec: str) -> str:
        return "***REDACTED***"

    def __bool__(self) -> bool:
        return bool(self._value)
