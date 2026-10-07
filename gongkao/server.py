"""本地数据服务：界面通过 HTTP 读写学习记录，只监听 127.0.0.1。

由 main.py 在后台线程里启动，窗口关闭时随进程一起退出。
这里只管 HTTP（访问控制、静态文件、原卷截图、PDF 分段下载、AI 流式输出）；
各接口的业务代码在 gongkao/api/*.py，用 @route 登记；学习记录数据库在 gongkao/userdb.py。
"""

import itertools
import json
import logging
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import ai, api, library, qdb, shizheng, userdb
from . import docs as docmod
from .paths import content_dir, web_dir
from .userdb import db, get_settings, init_db, now_str, rows  # noqa: F401 —— 兼容旧的调用方式

log = logging.getLogger("gongkao.server")

STATIC_DIR = str(web_dir())
CONTENT_DIR = str(content_dir())
HOST = "127.0.0.1"
# 固定端口优先：界面的地址不变；被占用时换一个空闲端口
PREFERRED_PORT = int(os.environ.get("GONGKAO_PORT", "27315"))

# 本次运行的会话令牌：打开界面（index.html）时写进 Cookie（SameSite=Strict），之后的接口请求都要带上。
# 别的网站发来的请求带不上这个 Cookie（跨站 + 不同主机名），也就改不了设置、读不走数据。
SESSION_TOKEN = secrets.token_urlsafe(32)
SESSION_COOKIE = "gk_session"
# 不需要会话的接口：启动时检查是否已经在运行
PUBLIC_API = {"/api/ping"}
# 收二进制请求体的接口（面试录音）
UPLOAD_API = {"/api/interviews/audio"}
MAX_UPLOAD = 50 << 20

api.load_all()


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "GongkaoPrep/1.0"

    def log_message(self, fmt, *args):
        # 只记接口请求（静态文件、截图太多）；send_error 传进来的第一个参数是状态码，不是请求行
        if "/api/" in str(args[0] if args else ""):
            log.debug(fmt, *args)

    # ---- helpers
    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def send_file(self, path, set_session=False):
        if not os.path.isfile(path):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        if set_session:
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}={SESSION_TOKEN}; Path=/; HttpOnly; SameSite=Strict")
        self.end_headers()
        self.wfile.write(body)

    def safe_join(self, base, rel):
        base = os.path.abspath(base)
        p = os.path.abspath(os.path.join(base, rel))
        try:
            return p if os.path.commonpath([base, p]) == base else None
        except ValueError:  # 不在同一个盘
            return None

    # ---- 访问控制：只接受本机界面发来的请求
    def host_ok(self):
        """Host 必须是本机地址（防 DNS 重绑定：恶意域名解析到 127.0.0.1 时，Host 是那个域名）。"""
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}") or host in getattr(self.server, "extra_hosts", ())

    def session_ok(self):
        try:
            m = SimpleCookie(self.headers.get("Cookie") or "").get(SESSION_COOKIE)
        except Exception:  # noqa: BLE001 —— 格式错误的 Cookie 当作没带
            return False
        return bool(m) and secrets.compare_digest(m.value, SESSION_TOKEN)

    def post_ok(self):
        """写接口额外要求：JSON 请求体（跨站的表单、简单请求发不出来），来源是本页面。

        上传录音的接口收音频（audio/*）：同样不是浏览器“简单请求”的类型，跨站发送要先预检，本服务不放行。
        """
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        path = urlparse(self.path).path
        if ctype != "application/json" and not (path in UPLOAD_API and ctype.startswith("audio/")):
            return False
        origin = (self.headers.get("Origin") or "").lower()
        if origin and origin != "http://" + (self.headers.get("Host") or "").strip().lower():
            return False
        return (self.headers.get("Sec-Fetch-Site") or "same-origin") in ("same-origin", "none")

    def deny(self, why):
        log.warning("拒绝 %s %s（Host=%s Origin=%s）：%s", self.command, self.path,
                    self.headers.get("Host"), self.headers.get("Origin"), why)
        self.send_json({"error": "请求被拒绝：" + why}, 403)

    def guard(self, path):
        """放行返回 True；不放行时已经回了 403。"""
        if not self.host_ok():
            self.deny("只接受本机访问")
            return False
        if path.startswith("/api/") and path not in PUBLIC_API and not self.session_ok():
            self.deny("会话无效，请重新打开软件窗口")
            return False
        if self.command == "POST" and not self.post_ok():
            self.deny("来源不明")
            return False
        return True

    # ---- routing
    def send_bytes(self, body, ctype, cache="no-cache", extra=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_crop(self, rest):
        """/api/crop/<文件id>/<页>/<x0,y0,x1,y1>.png —— 题目在原卷上的截图。"""
        m = re.match(r"^([\w-]+)/(\d+)/([\d.]+),([\d.]+),([\d.]+),([\d.]+)\.png$", rest)
        if not m:
            return self.send_error(HTTPStatus.BAD_REQUEST)
        target, _f = library.resolve(m.group(1))
        if not target:
            return self.send_error(HTTPStatus.NOT_FOUND)
        clip = tuple(float(m.group(i)) for i in range(3, 7))
        png = library.render_png(target, int(m.group(2)), clip=clip, zoom=2.2)
        self.send_bytes(png, "image/png", cache="max-age=86400")

    def send_recording(self, name):
        """/api/recording/<文件名> —— 面试练习的录音回放。"""
        from .api.notes import RECORDINGS

        if not re.fullmatch(r"[\w-]+\.(webm|ogg|wav|m4a)", name or ""):
            return self.send_error(HTTPStatus.BAD_REQUEST)
        path = RECORDINGS / name
        if not path.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        ctype = {"webm": "audio/webm", "ogg": "audio/ogg", "wav": "audio/wav", "m4a": "audio/mp4"}[name.rsplit(".", 1)[1]]
        self.send_bytes(path.read_bytes(), ctype, cache="no-cache")

    def send_docimg(self, rel):
        """/api/docimg/<文件id>/<图片名> —— 资料库文档里的插图。"""
        if not re.fullmatch(r"[\w-]+/[\w.-]+\.(jpg|jpeg|png|gif|bmp)", rel or ""):
            return self.send_error(HTTPStatus.BAD_REQUEST)
        path = docmod.IMG_DIR / rel
        if not path.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        self.send_bytes(path.read_bytes(), mimetypes.guess_type(str(path))[0] or "image/jpeg", cache="max-age=86400")

    def send_page(self, query):
        """/api/library/page?fid=…&p=… —— 资料某一页的整页图片（扫描件、缩略预览用）。"""
        target, _f = library.resolve((query.get("fid") or [""])[0])
        if not target or not target.lower().endswith(".pdf"):
            return self.send_error(HTTPStatus.NOT_FOUND)
        zoom = min(3.0, max(0.3, float((query.get("z") or ["1.6"])[0])))
        png = library.render_png(target, int((query.get("p") or ["0"])[0]), zoom=zoom)
        self.send_bytes(png, "image/png", cache="max-age=86400")

    def send_source(self, fid):
        """原文件（PDF 等），支持 Range，内置 PDF 阅读器可以边下边看几百页的大文件。"""
        target, f = library.resolve(fid)
        if not target:
            return self.send_error(HTTPStatus.NOT_FOUND)
        size = os.path.getsize(target)
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        start, end = 0, size - 1
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = int(rng.group(2)) if rng.group(2) else size - 1
            else:
                start = max(0, size - int(rng.group(2)))
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-cache")
        from urllib.parse import quote
        self.send_header("Content-Disposition", "inline; filename*=UTF-8''" + quote(os.path.basename(target)))
        self.end_headers()
        try:
            with open(target, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_HEAD(self):
        """PDF 阅读器会先发 HEAD 探文件大小和是否支持分段下载。"""
        path = unquote(urlparse(self.path).path)
        if not self.guard(path):
            return
        target = None
        if path.startswith("/api/library/file/"):
            target, _f = library.resolve(path[len("/api/library/file/"):].split("/")[0])
            if not target:
                return self.send_error(HTTPStatus.NOT_FOUND)
        self.send_response(200)
        if target:
            self.send_header("Content-Type", mimetypes.guess_type(target)[0] or "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(os.path.getsize(target)))
        else:
            self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        path = unquote(url.path)
        if not self.guard(path):
            return
        try:
            if path.startswith("/api/crop/"):
                return self.send_crop(path[len("/api/crop/"):])
            if path.startswith("/api/docimg/"):
                return self.send_docimg(path[len("/api/docimg/"):])
            if path == "/api/library/page":
                return self.send_page(parse_qs(url.query))
            if path.startswith("/api/library/file/"):
                return self.send_source(path[len("/api/library/file/"):].split("/")[0])
            if path.startswith("/api/recording/"):
                return self.send_recording(path[len("/api/recording/"):])
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as e:  # noqa: BLE001
            return self.send_json({"error": str(e)}, 500)
        if path.startswith("/api/"):
            return self.handle_api("GET", path, parse_qs(url.query), None)
        if path.startswith("/content/"):
            p = self.safe_join(CONTENT_DIR, path[len("/content/"):])
            return self.send_file(p) if p else self.send_error(HTTPStatus.FORBIDDEN)
        rel = path.lstrip("/") or "index.html"
        p = self.safe_join(STATIC_DIR, rel)
        if not p:
            return self.send_error(HTTPStatus.FORBIDDEN)
        if not os.path.isfile(p):
            p = os.path.join(STATIC_DIR, "index.html")
        self.send_file(p, set_session=os.path.basename(p) == "index.html")

    def do_POST(self):
        url = urlparse(self.path)
        path = unquote(url.path)
        if not self.guard(path):
            return
        if path in UPLOAD_API:
            return self.handle_upload(path, parse_qs(url.query))
        try:
            body = self.read_json()
        except (ValueError, UnicodeDecodeError):
            return self.send_json({"error": "请求内容不是有效的 JSON"}, 400)
        if path.startswith("/api/ai/"):
            return self.handle_ai(path[len("/api/ai/"):], body)
        return self.handle_api("POST", path, parse_qs(url.query), body)

    def handle_upload(self, path, query):
        """二进制上传（面试录音）：请求体是音频本身，参数放在查询串里。"""
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_UPLOAD:
            return self.send_json({"error": "录音为空或太大（上限 50 MB）"}, 400)
        data = self.rfile.read(n)
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        return self.handle_api("POST", path, query, {"_bytes": data, "_ctype": ctype})

    def handle_api(self, method, path, query, body):
        found = api.find(method, path)
        if not found:
            return self.send_json({"error": "接口不存在"}, 404)
        fn, write = found
        try:
            if write:
                with userdb.write_lock, db() as conn:
                    result = fn(api.Ctx(conn, query, body, self))
            else:
                with db() as conn:
                    result = fn(api.Ctx(conn, query, body, self))
        except KeyError as e:
            return self.send_json({"error": f"缺少参数：{e}"}, 400)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        except sqlite3.OperationalError as e:
            log.exception("数据库出错：%s %s", method, path)
            return self.send_json({"error": f"数据库忙或出错，请稍后再试（{e}）"}, 503)
        except Exception as e:  # noqa: BLE001 —— 本地单用户应用，把错误原样告诉前端，同时记进日志
            log.exception("接口出错：%s %s", method, path)
            return self.send_json({"error": str(e)}, 500)
        if result is None:
            return self.send_json({"error": "接口不存在"}, 404)
        self.send_json(result)

    # ---- AI（流式输出纯文本）
    def handle_ai(self, kind, body):
        with userdb.write_lock, db() as conn:
            settings = get_settings(conn, include_secret=True)
            history = rows(conn, "SELECT role, content FROM chats ORDER BY id DESC LIMIT 20")[::-1]
        try:
            prompt = ai.build_request(kind, body, history)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        limit = int(float(settings.get("ai_monthly_tokens") or 0))
        if limit > 0 and kind != "test":
            with db() as conn:
                used = conn.execute("SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM ai_usage WHERE day >= ?",
                                    (now_str()[:7] + "-01",)).fetchone()[0]
            if used >= limit:
                return self.send_json({"error": f"本月 AI 用量已达上限（{used} / {limit} tokens），可在设置里调高上限"}, 429)
        # 先取到第一段再发响应头：Key 错、地址错之类的问题能作为正常的错误返回给界面
        gen = ai.stream(settings, prompt)
        try:
            first = next(gen, "")
        except ai.AIError as e:
            return self.send_json({"error": str(e)}, 502)
        except Exception as e:  # noqa: BLE001
            return self.send_json({"error": f"AI 出错：{e}"}, 502)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        chunks = []
        try:
            for piece in itertools.chain([first], gen):
                if not piece:
                    continue
                chunks.append(piece)
                self.wfile.write(piece.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            gen.close()
            return
        except Exception as e:  # noqa: BLE001 —— 响应头已发出，只能把错误写进正文
            self.wfile.write(("\n\n[AI 出错] " + str(e)).encode("utf-8"))
            return
        u = prompt.get("usage") or {}
        with userdb.write_lock, db() as conn:
            conn.execute(
                "INSERT INTO ai_usage(day, provider, model, kind, input_tokens, output_tokens, estimated, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (now_str()[:10], u.get("provider"), u.get("model"), kind, u.get("input") or 0, u.get("output") or 0,
                 1 if u.get("estimated") else 0, now_str()),
            )
        if kind == "chat":
            with userdb.write_lock, db() as conn:
                conn.execute(
                    "INSERT INTO chats(role, content, created_at) VALUES ('user', ?, ?)",
                    (body.get("message") or "", now_str()),
                )
                conn.execute(
                    "INSERT INTO chats(role, content, created_at) VALUES ('assistant', ?, ?)",
                    ("".join(chunks), now_str()),
                )


def auto_build():
    """第一次运行（或资料目录还没整理过）时，在后台自动整理一遍资料文件夹。"""
    if os.environ.get("GONGKAO_NO_AUTOBUILD"):
        return
    with db() as conn:
        root = get_settings(conn).get("library_root") or ""
    if not root or not os.path.isdir(root):
        return
    if not library.CATALOG_PATH.exists():
        library.jobs.start("整理全部资料", lambda j: library.full_rebuild(root, j))
    elif (not docmod.DB_PATH.exists() or docmod.outdated()) and qdb.DB_PATH.exists():
        # 还没整理过，或者整理规则更新了（资料库文档的 VERSION 变了）：后台重新整理
        library.jobs.start("整理资料库文档", lambda j: library.build_docs(root, j))
    elif not qdb.DB_PATH.exists():
        # 从旧版本升级：目录已有，题库还没进数据库
        def upgrade(j):
            library.build_real(root, j)
            library.build_books(root, j)

        library.jobs.start("生成题库", upgrade)
    elif not shizheng.DB_PATH.exists():
        # 时政晨读是后来加的：已经整理过资料的，单独补整理这一块
        library.jobs.start("整理时政晨读", lambda j: library.build_shizheng(root, j))


def start_server():
    """初始化数据库并在后台线程启动服务，返回端口号。"""
    init_db()
    auto_build()
    try:
        server = ThreadingHTTPServer((HOST, PREFERRED_PORT), Handler)
    except OSError:
        server = ThreadingHTTPServer((HOST, 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]
