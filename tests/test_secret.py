"""API Key 加密保存。"""

import sys

import pytest

from gongkao import secret, server


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI 只在 Windows 上有")
def test_roundtrip():
    enc = secret.protect("sk-abc-123456789")
    assert enc.startswith("dpapi:") and "sk-abc" not in enc
    assert secret.unprotect(enc) == "sk-abc-123456789"
    assert secret.protect(enc) == enc  # 不会重复加密


def test_plain_and_broken():
    assert secret.unprotect("plain-key") == "plain-key"
    assert secret.unprotect("dpapi:not-base64!!") == ""
    assert secret.protect("") == ""


def test_key_stored_encrypted(client):
    client.post("/api/settings", {"ai_api_key": "sk-test-0000111122223333"})
    with server.db() as conn:
        raw = conn.execute("SELECT value FROM settings WHERE key='ai_api_key'").fetchone()[0]
        assert "sk-test" not in raw
        assert server.get_settings(conn, include_secret=True)["ai_api_key"] == "sk-test-0000111122223333"
    _s, s, _ = client.get("/api/settings")
    assert s["ai_api_key"] == "" and s["ai_key_saved"] and s["ai_key_hint"].endswith("3333")
    _s, exp, _ = client.get("/api/export")
    assert "sk-test" not in str(exp)
    client.post("/api/settings", {"ai_clear_key": True})


def test_plaintext_migrated_on_start(httpd):
    with server.db() as conn:
        conn.execute("UPDATE settings SET value='sk-legacy-plain-key' WHERE key='ai_api_key'")
    server.init_db()
    with server.db() as conn:
        raw = conn.execute("SELECT value FROM settings WHERE key='ai_api_key'").fetchone()[0]
        assert raw != "sk-legacy-plain-key"
        assert server.get_settings(conn, include_secret=True)["ai_api_key"] == "sk-legacy-plain-key"
        conn.execute("UPDATE settings SET value='' WHERE key='ai_api_key'")
