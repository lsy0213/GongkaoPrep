"""服务器模式（--server）：没登录什么都看不到；密码登录后能用普通功能，管理类接口不行；Host、来源、输错次数都有限制。"""

import http.client
import threading
from urllib.parse import urlencode

import pytest

from gongkao import remote, server

HOST = "example.test"
PW = "correct horse battery"


@pytest.fixture()
def srv(httpd, monkeypatch):
    monkeypatch.setenv("GONGKAO_PUBLIC_HOSTS", HOST)
    remote.set_password(PW)
    s = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    s.daemon_threads = True
    s.remote = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_address[1]
    s.shutdown()
    s.server_close()
    remote._fails.clear()


def req(port, path, method="GET", cookie="", body=None, headers=None, host=HOST, ip="203.0.113.7"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": host, "X-Real-IP": ip}
    if cookie:
        h["Cookie"] = cookie
    h.update(headers or {})
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    return r.status, data, {k.lower(): v for k, v in r.getheaders()}


def login(port, pw=PW, ip="203.0.113.7", origin=f"https://{HOST}"):
    return req(port, "/login", "POST", body=urlencode({"password": pw}), ip=ip,
               headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": origin})


def test_needs_login(srv):
    status, _b, hdrs = req(srv, "/")
    assert status == 302 and hdrs["location"] == "/login"
    status, body, _ = req(srv, "/api/dashboard")
    assert status == 401 and b'"login": true' in body
    status, body, _ = req(srv, "/login")
    assert status == 200 and "密码".encode() in body
    assert req(srv, "/api/ping")[0] == 200
    # GET /logout 不能拿来绕过登录看页面
    assert req(srv, "/logout")[0] == 403


def test_login_flow(srv):
    status, _b, hdrs = login(srv)
    assert status == 302 and hdrs["location"] == "/"
    sc = hdrs["set-cookie"]
    assert "gk_remote=" in sc and "Secure" in sc and "HttpOnly" in sc and "SameSite=Strict" in sc
    cookie = sc.split(";")[0]
    status, _b, hdrs = req(srv, "/", cookie=cookie)
    assert status == 200 and "gk_session" not in hdrs.get("set-cookie", "")
    assert req(srv, "/api/dashboard", cookie=cookie)[0] == 200
    status, body, _ = req(srv, "/api/session", cookie=cookie)
    assert b'"remote"' in body
    # 写接口：JSON + 同源（https）
    ok = req(srv, "/api/prefs", "POST", cookie, b'{"x": 1}', {"Content-Type": "application/json", "Origin": f"https://{HOST}"})
    assert ok[0] == 200
    bad = req(srv, "/api/prefs", "POST", cookie, b'{"x": 1}', {"Content-Type": "application/json", "Origin": "https://evil.test"})
    assert bad[0] == 403
    # 管理类接口不行
    for p in ("/api/lan/status", "/api/export", "/api/diagnostics", "/api/storage/clean"):
        assert req(srv, p, cookie=cookie)[0] == 403
    # 退出所有设备：旧 Cookie 失效
    status, _b, hdrs = req(srv, "/logout?all=1", "POST", cookie, b"",
                           {"Content-Type": "application/x-www-form-urlencoded", "Origin": f"https://{HOST}"})
    assert status == 302 and "Max-Age=0" in hdrs["set-cookie"]
    assert req(srv, "/api/dashboard", cookie=cookie)[0] == 401


def test_wrong_host_and_origin(srv):
    cookie = login(srv)[2]["set-cookie"].split(";")[0]
    assert req(srv, "/", cookie=cookie, host="attacker.test")[0] == 403
    assert login(srv, origin="https://evil.test")[0] == 403
    # 手机浏览器有时在 Host 里带上默认端口
    assert req(srv, "/", cookie=cookie, host=f"{HOST}:443")[0] == 200
    assert req(srv, "/", cookie=cookie, host=f"{HOST}:8443")[0] == 403


def test_lockout(srv):
    for _ in range(remote.MAX_FAILS):
        assert login(srv, "wrong password", ip="198.51.100.9")[0] == 403
    assert login(srv, ip="198.51.100.9")[0] == 429  # 密码对了也要等
    assert login(srv, ip="198.51.100.10")[0] == 302  # 别的 IP 不受影响


def test_password_rules(httpd):
    with pytest.raises(ValueError):
        remote.set_password("short")
    remote.set_password(PW)
    assert remote.check_password(PW) and not remote.check_password(PW + "x")
