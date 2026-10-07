"""手机访问（局域网）：必须先配对；配对后能用普通功能，管理类接口不行；Host 必须是局域网地址。"""

import http.client

import pytest

from gongkao import lan, server

pytestmark = pytest.mark.lan


@pytest.fixture()
def lan_srv(httpd):
    if lan.local_ip().startswith("127."):
        pytest.skip("这台电脑没有连局域网")
    st = lan.start(server.Handler)
    yield st
    lan.stop()


def req(st, path, cookie="", host=None, method="GET", body=None, headers=None):
    c = http.client.HTTPConnection(st["ip"], st["port"], timeout=10)
    h = {"Host": host or f"{st['ip']}:{st['port']}"}
    if cookie:
        h["Cookie"] = cookie
    h.update(headers or {})
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    return r.status, data, {k.lower(): v for k, v in r.getheaders()}


def test_pairing_flow(lan_srv):
    st = lan_srv
    status, body, _ = req(st, "/")
    assert status == 403 and "配对".encode() in body
    status, _b, _ = req(st, "/pair?code=wrong")
    assert status == 403
    code = st["url"].split("code=")[1]
    status, _b, hdrs = req(st, f"/pair?code={code}")
    assert status == 302 and hdrs["location"] == "/" and "gk_lan=" in hdrs["set-cookie"]
    cookie = hdrs["set-cookie"].split(";")[0]
    status, _b, hdrs = req(st, "/", cookie)
    assert status == 200 and "gk_session" not in hdrs.get("set-cookie", "")  # 不把电脑上的会话发给手机
    status, _b, _ = req(st, "/api/cards", cookie)
    assert status == 200
    # 管理类接口不行
    for p in ("/api/lan/status", "/api/export", "/api/diagnostics"):
        assert req(st, p, cookie)[0] == 403
    status, _b, _ = req(st, "/api/backups/restore", cookie, method="POST", body=b'{"name":"x"}',
                        headers={"Content-Type": "application/json"})
    assert status == 403
    # DNS 重绑定：Host 不是局域网地址
    assert req(st, "/", cookie, host=f"evil.example:{st['port']}")[0] == 403
    # 重置配对后旧 Cookie 失效
    lan.reset_token()
    assert req(st, "/api/cards", cookie)[0] == 403


def test_desktop_controls(client):
    _s, st, _ = client.get("/api/lan/status")
    assert st["running"] in (True, False)
