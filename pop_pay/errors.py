"""
pop-pay centralized error model.

Spec: docs/ERROR_CODES.md (shared with pop-pay-npm TypeScript repo).
Class names and codes are parity with TS — do not diverge.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Optional


class PopPayError(Exception):
    """Base class for all pop-pay errors.

    Attributes:
        code: stable machine-readable identifier (e.g. VAULT_NOT_FOUND)
        message: human-readable summary
        remediation: optional one-line fix hint
        cause: wrapped underlying exception (use __cause__ semantics)
    """

    code: str = "UNKNOWN"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        remediation: Optional[str] = None,
        cause: Optional[BaseException] = None,
    ):
        super().__init__(message)
        if code is not None:
            self.code = code
        self.message = message
        self.remediation = remediation
        if cause is not None:
            self.__cause__ = cause

    def to_dict(self) -> dict[str, Any]:
        cause = self.__cause__
        return {
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
            "cause": str(cause) if cause is not None else None,
        }


# Vault ----------------------------------------------------------------------
class PopPayVaultError(PopPayError):
    pass


class VaultNotFound(PopPayVaultError):
    code = "VAULT_NOT_FOUND"

    def __init__(self, message: str = "No vault found.", **kw):
        kw.setdefault("remediation", "Run: pop-pay init-vault")
        super().__init__(message, **kw)


class VaultDecryptFailed(PopPayVaultError):
    code = "VAULT_DECRYPT_FAILED"

    def __init__(
        self,
        message: str = "Failed to decrypt vault — wrong key or corrupted vault.",
        **kw,
    ):
        kw.setdefault("remediation", "Re-run: pop-pay init-vault")
        super().__init__(message, **kw)


class VaultLocked(PopPayVaultError):
    code = "VAULT_LOCKED"

    def __init__(
        self,
        message: str = "Vault is locked (passphrase mode, no key in keyring).",
        **kw,
    ):
        kw.setdefault("remediation", "Run: pop-unlock")
        super().__init__(message, **kw)


# Config ---------------------------------------------------------------------
class PopPayConfigError(PopPayError):
    pass


class MissingEnvVar(PopPayConfigError):
    code = "CONFIG_MISSING_ENV_VAR"

    def __init__(self, name: str, **kw):
        kw.setdefault("remediation", "See docs/ENV_REFERENCE.md")
        super().__init__(f"Required env var not set: {name}", **kw)


class InvalidPolicyJSON(PopPayConfigError):
    code = "CONFIG_INVALID_POLICY_JSON"

    def __init__(self, name: str, **kw):
        kw.setdefault("remediation", "Fix the JSON value in your policy .env")
        super().__init__(f"Invalid JSON in env var: {name}", **kw)


class CategoryParseError(PopPayConfigError):
    code = "CONFIG_CATEGORY_PARSE_ERROR"

    def __init__(self, message: str, **kw):
        kw.setdefault("remediation", "See docs/CATEGORIES_COOKBOOK.md")
        super().__init__(message, **kw)


# Guardrail ------------------------------------------------------------------
class PopPayGuardrailError(PopPayError):
    pass


class Layer1Reject(PopPayGuardrailError):
    code = "GUARDRAIL_LAYER1_REJECT"

    def __init__(self, reason: str, **kw):
        super().__init__(f"Layer 1 rejected intent: {reason}", **kw)


class Layer2Reject(PopPayGuardrailError):
    code = "GUARDRAIL_LAYER2_REJECT"

    def __init__(self, reason: str, **kw):
        super().__init__(f"Layer 2 rejected intent: {reason}", **kw)


class ProbeTimeout(PopPayGuardrailError):
    code = "GUARDRAIL_PROBE_TIMEOUT"

    def __init__(self, message: str = "Guardrail probe exceeded deadline.", **kw):
        super().__init__(message, **kw)


# Injector -------------------------------------------------------------------
class PopPayInjectorError(PopPayError):
    pass


class CDPConnectFailed(PopPayInjectorError):
    code = "INJECTOR_CDP_CONNECT_FAILED"

    def __init__(self, url: str, **kw):
        kw.setdefault("remediation", "Start Chrome with: pop-launch")
        super().__init__(f"CDP connect failed: {url}", **kw)


class ChromiumNotFound(PopPayInjectorError):
    code = "INJECTOR_CHROMIUM_NOT_FOUND"

    def __init__(self, message: str = "No Chromium-family browser found.", **kw):
        kw.setdefault("remediation", "Install Chrome or set CHROME_PATH")
        super().__init__(message, **kw)


class FrameNotFound(PopPayInjectorError):
    code = "INJECTOR_FRAME_NOT_FOUND"

    def __init__(self, message: str = "Target iframe not present on page.", **kw):
        super().__init__(message, **kw)


class ShadowDOMSkipped(PopPayInjectorError):
    code = "INJECTOR_SHADOW_DOM_SKIPPED"

    def __init__(
        self, message: str = "Shadow DOM detected; skipped for safety.", **kw
    ):
        super().__init__(message, **kw)


# LLM ------------------------------------------------------------------------
class PopPayLLMError(PopPayError):
    pass


class ProviderUnreachable(PopPayLLMError):
    code = "LLM_PROVIDER_UNREACHABLE"

    def __init__(self, provider: str, **kw):
        kw.setdefault("remediation", "Check network + API key")
        super().__init__(f"LLM provider unreachable: {provider}", **kw)


class InvalidResponse(PopPayLLMError):
    code = "LLM_INVALID_RESPONSE"

    def __init__(self, detail: str, **kw):
        super().__init__(f"LLM returned malformed response: {detail}", **kw)


class RetryExhausted(PopPayLLMError):
    code = "LLM_RETRY_EXHAUSTED"

    def __init__(self, message: str = "All LLM retries failed.", **kw):
        super().__init__(message, **kw)


# Unknown --------------------------------------------------------------------
class PopPayUnknownError(PopPayError):
    code = "UNKNOWN"

    def __init__(self, cause: BaseException):
        super().__init__(str(cause) or "Unknown error", cause=cause)


# CLI handler ----------------------------------------------------------------
def handle_cli_error(err: BaseException, *, as_json: bool = False) -> "None":
    """Central CLI error handler. Use in entry-point try/except blocks.

    Renders human or JSON output to stderr, then sys.exit(1) for PopPayError
    or sys.exit(2) for unknown.
    """
    typed = err if isinstance(err, PopPayError) else PopPayUnknownError(err)

    if as_json:
        sys.stderr.write(json.dumps(typed.to_dict()) + "\n")
    else:
        sys.stderr.write(f"pop-pay: {typed.code}\n")
        sys.stderr.write(f"  {typed.message}\n")
        if typed.remediation:
            sys.stderr.write(f"  \u2192 {typed.remediation}\n")

    sys.exit(2 if isinstance(typed, PopPayUnknownError) else 1)
