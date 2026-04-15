"""
S0.7 F6(A): cross-process MCP transport split.

Threat closed: a sibling process on the same host attaches to the MCP server
post-launch, bypassing the launcher's policy context (allowed categories,
per-tx / daily caps, blackout mode).

Architecture:
- Launcher path = stdio pipe (default; preserves Claude Desktop config compat).
- Attacher path = StreamableHTTP on 127.0.0.1:<ephemeral>, gated by Bearer token.
- Token is 256-bit random, generated at server start, written to
  ~/.config/pop-pay/.attach_token mode 0600. Ephemeral port written to
  ~/.config/pop-pay/.attach_port mode 0600. Both rotate on every restart.

The Bearer-auth middleware rejects with 401 BEFORE any MCP frame is parsed.
"""
from __future__ import annotations

import os
import secrets
import socket
from pathlib import Path

VAULT_DIR = Path.home() / ".config" / "pop-pay"
TOKEN_PATH = VAULT_DIR / ".attach_token"
PORT_PATH = VAULT_DIR / ".attach_port"

TOKEN_BYTES = 32  # 256-bit


def generate_attach_token() -> str:
    """Return a fresh 256-bit hex token."""
    return secrets.token_hex(TOKEN_BYTES)


def write_attach_artifacts(token: str, port: int) -> None:
    """Persist token + port to ~/.config/pop-pay (mode 0600 each)."""
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    VAULT_DIR.chmod(0o700)
    TOKEN_PATH.write_text(token)
    TOKEN_PATH.chmod(0o600)
    PORT_PATH.write_text(str(port))
    PORT_PATH.chmod(0o600)


def clear_attach_artifacts() -> None:
    """Best-effort removal of token + port files (called on graceful shutdown)."""
    for p in (TOKEN_PATH, PORT_PATH):
        try:
            if p.exists():
                size = p.stat().st_size
                if size > 0:
                    with p.open("r+b") as f:
                        f.write(b"\x00" * size)
                        f.flush()
                        os.fsync(f.fileno())
                p.unlink()
        except OSError:
            pass


def pick_ephemeral_port() -> int:
    """Bind-and-release an OS-chosen port on 127.0.0.1 to avoid race-prone fixed ports."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def make_bearer_middleware(expected_token: str):
    """Return a Starlette middleware class that requires `Authorization: Bearer <token>`.

    Rejects missing/wrong tokens with 401 before any MCP frame is parsed.
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    expected = f"Bearer {expected_token}"

    class BearerAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            auth = request.headers.get("authorization", "")
            if not secrets.compare_digest(auth, expected):
                return JSONResponse(
                    {"error": "unauthorized: missing or invalid Bearer token"},
                    status_code=401,
                )
            return await call_next(request)

    return BearerAuthMiddleware
