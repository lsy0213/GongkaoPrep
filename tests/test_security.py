"""本地服务的访问控制：只接受本机界面发来的请求。"""


def test_index_sets_session_cookie(anon):
    status, _body, hdrs = anon.get("/")
    assert status == 200
    assert "gk_session=" in hdrs.get("set-cookie", "")
    assert "SameSite=Strict" in hdrs["set-cookie"]
    assert "HttpOnly" in hdrs["set-cookie"]


def test_api_requires_session(anon):
    status, body, _ = anon.get("/api/settings")
    assert status == 403
    assert "会话" in body["error"]


def test_ping_is_public(anon):
    status, body, _ = anon.get("/api/ping")
    assert status == 200 and body["app"] == "gongkao-prep"


def test_session_allows_api(client):
    status, body, _ = client.get("/api/settings")
    assert status == 200 and "guokao_date" in body


def test_foreign_host_rejected(httpd):
    """DNS 重绑定：恶意域名解析到 127.0.0.1，浏览器发来的 Host 是那个域名。"""
    from conftest import Client

    evil = Client(httpd.server_address[1], host="evil.example:%d" % httpd.server_address[1])
    status, _body, hdrs = evil.get("/")
    assert status == 403
    assert "set-cookie" not in hdrs


def test_cross_site_post_rejected(client):
    """别的网站用 fetch(no-cors) 发 text/plain 的请求，想改 AI 服务地址偷 Key。"""
    status, _b, _ = client.request(
        "POST", "/api/settings", body='{"ai_base_url": "http://evil.example"}',
        headers={"Content-Type": "text/plain"},
    )
    assert status == 403
    status, _b, _ = client.post("/api/settings", {"ai_base_url": "http://evil.example"},
                                headers={"Origin": "http://evil.example"})
    assert status == 403
    status, _b, _ = client.post("/api/settings", {"ai_base_url": "http://evil.example"},
                                headers={"Sec-Fetch-Site": "cross-site"})
    assert status == 403
    _s, settings, _ = client.get("/api/settings")
    assert settings["ai_base_url"] != "http://evil.example"


def test_same_origin_post_allowed(client):
    port = client.port
    status, body, _ = client.post("/api/prefs", {"test-key": 1},
                                  headers={"Origin": f"http://127.0.0.1:{port}", "Sec-Fetch-Site": "same-origin"})
    assert status == 200 and body["ok"]
    client.post("/api/prefs", {"test-key": None})


def test_static_path_traversal(client):
    status, _b, _ = client.get("/content/../gongkao/server.py")
    assert status in (403, 404) or "SESSION_TOKEN" not in str(_b)
    status, body, _ = client.get("/..%5c..%5cgongkao%5cserver.py")
    assert "SESSION_TOKEN" not in str(body)
