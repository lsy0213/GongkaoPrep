"""测试公共设置：用临时数据目录启动一个真实的本地服务，不碰本机的学习数据。"""

import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="gongkao-test-")
os.environ["GONGKAO_DATA_DIR"] = TMP
os.environ["GONGKAO_NO_AUTOBUILD"] = "1"
sys.path.insert(0, str(ROOT))

from gongkao import server  # noqa: E402


class Client:
    """最小的 HTTP 客户端：自动带上会话 Cookie，返回 (状态码, 解析后的 JSON 或文本, 响应头)。"""

    def __init__(self, port, host=None):
        self.port = port
        self.host = host or f"127.0.0.1:{port}"
        self.cookie = ""

    def request(self, method, path, body=None, headers=None, raw=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": self.host}
        if self.cookie:
            h["Cookie"] = self.cookie
        data = None
        if body is not None:
            data = body if isinstance(body, (bytes, str)) else json.dumps(body)
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        payload = r.read()
        hdrs = {k.lower(): v for k, v in r.getheaders()}
        conn.close()
        if "set-cookie" in hdrs:
            self.cookie = hdrs["set-cookie"].split(";")[0]
        if raw:
            return r.status, payload, hdrs
        try:
            return r.status, json.loads(payload.decode("utf-8")), hdrs
        except ValueError:
            return r.status, payload.decode("utf-8", "replace"), hdrs

    def open_app(self):
        """像界面一样先打开首页，拿到会话 Cookie。"""
        return self.request("GET", "/")

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body if body is not None else {}, **kw)


@pytest.fixture(scope="session")
def httpd():
    server.init_db()
    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)


@pytest.fixture()
def client(httpd):
    c = Client(httpd.server_address[1])
    c.open_app()
    return c


@pytest.fixture()
def anon(httpd):
    """没打开过界面的客户端（没有会话 Cookie）。"""
    return Client(httpd.server_address[1])
