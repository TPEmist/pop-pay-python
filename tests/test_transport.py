"""S0.7 F6(A) transport split: token gen, file persistence, Bearer middleware."""
import os
import socket
import stat
import pytest
from pathlib import Path


def test_generate_attach_token_is_64_hex_chars():
    from pop_pay.transport import generate_attach_token
    t = generate_attach_token()
    assert len(t) == 64
    int(t, 16)  # must parse as hex


def test_generate_attach_token_is_unique():
    from pop_pay.transport import generate_attach_token
    assert generate_attach_token() != generate_attach_token()


def test_write_attach_artifacts_mode_0600(tmp_path, monkeypatch):
    import pop_pay.transport as t
    monkeypatch.setattr(t, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(t, "TOKEN_PATH", tmp_path / ".attach_token")
    monkeypatch.setattr(t, "PORT_PATH", tmp_path / ".attach_port")
    t.write_attach_artifacts("deadbeef" * 8, 12345)
    for p in (t.TOKEN_PATH, t.PORT_PATH):
        assert p.exists()
        mode = stat.S_IMODE(p.stat().st_mode)
        assert mode == 0o600, f"{p.name} should be 0600, got {oct(mode)}"
    assert t.TOKEN_PATH.read_text() == "deadbeef" * 8
    assert t.PORT_PATH.read_text() == "12345"


def test_clear_attach_artifacts_removes_files(tmp_path, monkeypatch):
    import pop_pay.transport as t
    monkeypatch.setattr(t, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(t, "TOKEN_PATH", tmp_path / ".attach_token")
    monkeypatch.setattr(t, "PORT_PATH", tmp_path / ".attach_port")
    t.write_attach_artifacts("x" * 64, 9999)
    assert t.TOKEN_PATH.exists() and t.PORT_PATH.exists()
    t.clear_attach_artifacts()
    assert not t.TOKEN_PATH.exists()
    assert not t.PORT_PATH.exists()


def test_clear_attach_artifacts_idempotent(tmp_path, monkeypatch):
    import pop_pay.transport as t
    monkeypatch.setattr(t, "TOKEN_PATH", tmp_path / "missing-token")
    monkeypatch.setattr(t, "PORT_PATH", tmp_path / "missing-port")
    t.clear_attach_artifacts()  # must not raise


def test_pick_ephemeral_port_returns_available_port():
    from pop_pay.transport import pick_ephemeral_port
    port = pick_ephemeral_port()
    assert 1024 < port < 65536
    # Must be re-bindable (i.e. port was released)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
    finally:
        s.close()


@pytest.mark.asyncio
async def test_bearer_middleware_rejects_missing_token():
    pytest.importorskip("starlette")
    from pop_pay.transport import make_bearer_middleware
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import PlainTextResponse
    from starlette.testclient import TestClient

    async def ok(_): return PlainTextResponse("ok")
    mw_cls = make_bearer_middleware("secrettoken")
    app = Starlette(routes=[Route("/", ok)])
    app.add_middleware(mw_cls)
    client = TestClient(app)

    r = client.get("/")
    assert r.status_code == 401
    r = client.get("/", headers={"Authorization": "Bearer wrongtoken"})
    assert r.status_code == 401
    r = client.get("/", headers={"Authorization": "Bearer secrettoken"})
    assert r.status_code == 200


def test_bearer_middleware_constant_time_compare():
    """compare_digest path — sanity check that wrong-but-same-length is rejected."""
    pytest.importorskip("starlette")
    from pop_pay.transport import make_bearer_middleware
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import PlainTextResponse
    from starlette.testclient import TestClient

    async def ok(_): return PlainTextResponse("ok")
    token = "a" * 64
    wrong = "b" * 64
    app = Starlette(routes=[Route("/", ok)])
    app.add_middleware(make_bearer_middleware(token))
    client = TestClient(app)
    assert client.get("/", headers={"Authorization": f"Bearer {wrong}"}).status_code == 401
    assert client.get("/", headers={"Authorization": f"Bearer {token}"}).status_code == 200
