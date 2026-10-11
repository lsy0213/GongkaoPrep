"""服务器模式（python main.py --server）：放到云服务器上，手机和别的电脑用浏览器从外网打开。

前面由 Nginx 做 HTTPS（见 tools/deploy/），本服务只听 127.0.0.1。只有一个使用者，用密码登录：
- 密码在服务器上用命令行设：python main.py --set-password（只存加盐的 scrypt 哈希）；
- 登录成功发一个长期 Cookie（gk_remote：HttpOnly、Secure、SameSite=Strict，180 天）；改密码或「退出所有设备」会换掉它；
- 每个请求（包括页面本身）都要带这个 Cookie，没带就跳到登录页；Host 必须是部署时填的公网地址（GONGKAO_PUBLIC_HOSTS）；
- 同一个 IP 10 分钟内输错 5 次，锁 10 分钟；
- 改数据位置、恢复备份、导入、整理资料、手机访问等管理类接口一律不能用（和局域网手机一样，见 lan.DENY_PREFIXES）。
"""

import hashlib
import html
import os
import secrets
import threading
import time

from .userdb import db

REMOTE_COOKIE = "gk_remote"
COOKIE_AGE = 180 * 86400
MAX_FAILS, WINDOW = 5, 600

_state = {"token": ""}
_fails = {}
_lock = threading.Lock()


def allowed_hosts():
    """浏览器地址栏里的主机（IP 或域名，非 443 端口要带上端口），逗号分隔。"""
    return tuple(h.strip().lower() for h in os.environ.get("GONGKAO_PUBLIC_HOSTS", "").split(",") if h.strip())


def _get(key):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row and row[0] else ""


def _put(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, value))


def _hash(password, salt, n=2**14, r=8, p=1):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=64 << 20, dklen=32)


def has_password():
    return bool(_get("remote_pw"))


def set_password(password):
    """设新密码，同时换掉登录凭证（已经登录的设备都要重新登录）。"""
    if len(password) < 8:
        raise ValueError("密码至少 8 位")
    salt = secrets.token_bytes(16)
    stored = f"scrypt$16384$8$1${salt.hex()}${_hash(password, salt).hex()}"
    tok = secrets.token_urlsafe(32)
    with db() as conn:
        _put(conn, "remote_pw", stored)
        _put(conn, "remote_token", tok)
    _state["token"] = tok


def check_password(password):
    stored = _get("remote_pw")
    try:
        _algo, n, r, p, salt, want = stored.split("$")
        got = _hash(password or "", bytes.fromhex(salt), int(n), int(r), int(p))
    except ValueError:
        return False
    return secrets.compare_digest(got.hex(), want)


def token():
    if not _state["token"]:
        tok = _get("remote_token")
        if not tok:
            tok = secrets.token_urlsafe(32)
            with db() as conn:
                _put(conn, "remote_token", tok)
        _state["token"] = tok
    return _state["token"]


def token_ok(value):
    return bool(value) and secrets.compare_digest(value, token())


def reset_token():
    tok = secrets.token_urlsafe(32)
    with db() as conn:
        _put(conn, "remote_token", tok)
    _state["token"] = tok


def locked(ip):
    """这个 IP 是否因为输错太多次被锁着；返回还要等的秒数（0 表示没锁）。"""
    now = time.time()
    with _lock:
        hits = [t for t in _fails.get(ip, []) if now - t < WINDOW]
        _fails[ip] = hits
        return int(WINDOW - (now - hits[0])) + 1 if len(hits) >= MAX_FAILS else 0


def record_fail(ip):
    with _lock:
        _fails.setdefault(ip, []).append(time.time())
        if len(_fails) > 10000:  # 不让一堆不同 IP 把内存撑大
            _fails.clear()


def clear_fails(ip):
    with _lock:
        _fails.pop(ip, None)


def cookie_header(value, max_age=COOKIE_AGE):
    return f"{REMOTE_COOKIE}={value}; Path=/; Max-Age={max_age}; HttpOnly; Secure; SameSite=Strict"


def login_page(error=""):
    """登录页：和白瓷星轨一个样子的一张小卡片，只有一个密码框。"""
    msg = f"<p class='err'>{html.escape(error)}</p>" if error else ""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#EFEEEB">
<title>登录 · 上岸备考</title><link rel="icon" href="/img/icon-192.png" type="image/png"><link rel="apple-touch-icon" href="/img/apple-touch-icon.png">
<style>
:root {{ --bg: #EFEEEB; --card: rgba(250, 250, 248, .9); --ink: #292A27; --ink3: #8A8983; --line: #E3E1DB; --gold: #A68B52; --bad: #A8473D; color-scheme: light; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg: #141414; --card: rgba(29, 29, 29, .9); --ink: #EEEDEA; --ink3: #8F8E8A; --line: #33322F; --bad: #E58B7F; color-scheme: dark; }} }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 16px; color: var(--ink);
  background: radial-gradient(120% 90% at 60% 0%, color-mix(in srgb, var(--bg) 60%, #fff), var(--bg) 70%) fixed, var(--bg);
  font: 16px/1.7 "Iowan Old Style", "Palatino Linotype", "Noto Serif SC", "Songti SC", "STSong", serif; }}
form {{ width: min(100%, 360px); padding: 32px 28px 26px; border-radius: 22px; background: var(--card); border: 1px solid var(--line);
  box-shadow: 0 1px 2px rgba(40, 38, 34, .04), 0 22px 44px -26px rgba(40, 38, 34, .4); }}
.logo {{ display: block; width: 64px; height: 64px; margin: 0 0 18px; border-radius: 15px; box-shadow: 0 8px 18px -10px rgba(40, 38, 34, .45); }}
h1 {{ margin: 0 0 4px; font: 700 26px/1.3 "Didot", "Bodoni 72", "Noto Serif SC", "Songti SC", serif; letter-spacing: .2em; }}
p {{ margin: 0 0 18px; color: var(--ink3); font-size: 14px; }}
.line {{ height: 1px; margin: 0 0 20px; background: linear-gradient(90deg, var(--gold), #DCC797 30%, transparent 85%); opacity: .7; }}
input {{ width: 100%; padding: 11px 14px; border-radius: 14px; border: 1px solid var(--line); background: transparent; color: inherit; font: inherit; }}
input:focus {{ outline: none; border-color: var(--gold); box-shadow: 0 0 0 3px rgba(181, 154, 98, .18); }}
button {{ width: 100%; margin-top: 14px; padding: 10px; border: 0; border-radius: 999px; cursor: pointer; color: #292A27; font-family: inherit; font-size: 16px; font-weight: 600; letter-spacing: .3em;
  background: linear-gradient(180deg, #fff, rgba(255, 255, 255, .7));
  box-shadow: inset 0 1px 1px #fff, inset 0 -1px 2px rgba(120, 100, 60, .14), 0 0 0 .5px rgba(40, 38, 34, .16), 0 6px 14px -6px rgba(40, 38, 34, .3); }}
.err {{ margin: 12px 0 0; color: var(--bad); font-size: 14px; }}
</style></head><body>
<form method="post" action="/login" autocomplete="on">
<img class="logo" src="/img/logo-porcelain.png" alt="" width="64" height="64"><h1>上岸备考</h1><p>公考小窝 · 输入密码继续</p><div class="line"></div>
<input type="text" name="username" value="me" autocomplete="username" hidden>
<input type="password" name="password" placeholder="密码" autocomplete="current-password" required autofocus aria-label="密码">
<button type="submit">登录</button>{msg}
</form></body></html>"""
