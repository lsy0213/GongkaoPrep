"""手机访问（局域网）：同一个 Wi-Fi 下用手机扫码打开，碎片时间背闪卡、刷时政、做题。

默认关闭。打开后另起一个监听局域网地址的服务（和本机窗口用的 127.0.0.1 服务分开）：
- 手机第一次要扫电脑上显示的二维码配对：二维码里带一次性的配对码，配对成功后手机拿到一个长期的 Cookie；
- 局域网来的每个请求（包括页面本身）都要带这个 Cookie，Host 必须是电脑的局域网地址（防 DNS 重绑定）；
- 改数据位置、恢复备份、导入、打开电脑上的文件、控制手机访问等管理类接口，手机上一律不能用；
- “重置配对”会换掉 Cookie，已经配对的手机都要重新扫码。
"""

import secrets
import socket
import sys
import threading

from .userdb import db

LAN_COOKIE = "gk_lan"
# 手机上不能用的接口（前缀）
DENY_PREFIXES = (
    "/api/lan/", "/api/datadir/", "/api/backups/restore", "/api/import", "/api/library/open", "/api/storage/",
    "/api/positions/upload", "/api/positions/applicants", "/api/positions/delete", "/api/jobs/", "/api/diagnostics",
    "/api/export", "/api/update/",
)

_state = {"server": None, "thread": None, "port": 0, "ip": "", "pair_code": ""}
_lock = threading.Lock()


def _private(ip):
    """家庭 / 公司局域网常用的私有地址；排除代理软件的虚拟网卡（198.18.x）、自动分配地址（169.254.x）。"""
    try:
        a, b = (int(x) for x in ip.split(".")[:2])
    except ValueError:
        return False
    return a == 192 and b == 168 or a == 10 or a == 172 and 16 <= b <= 31


def _gateway_ips():
    """Windows：有默认网关、已连接的网卡的地址（真正连着路由器的 Wi-Fi / 网线，不是虚拟机、WSL 的虚拟网卡）。"""
    if sys.platform != "win32":
        return []
    import subprocess

    cmd = ("Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq 'Up' } "
           "| ForEach-Object { $_.IPv4Address.IPAddress }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, text=True,
                             timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [x.strip() for x in out.split() if x.strip()]


_cand = {"at": 0.0, "ips": []}


def candidate_ips():
    """可以给手机用的地址，最可能对的排在前面（查网卡要几秒，结果缓存 2 分钟）。"""
    import time

    if time.time() - _cand["at"] < 120 and _cand["ips"]:
        return _cand["ips"]
    try:
        addrs = {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        addrs = set()
    preferred = [ip for ip in _gateway_ips() if _private(ip)]
    rest = sorted((ip for ip in addrs if _private(ip) and ip not in preferred),
                  key=lambda ip: (not ip.startswith("192.168."), ip))
    _cand.update(at=time.time(), ips=preferred + rest)
    return _cand["ips"]


def local_ip():
    ips = candidate_ips()
    return ips[0] if ips else "127.0.0.1"


def lan_token():
    """长期的配对令牌，存在设置里（重启后已配对的手机不用重新扫码）。"""
    if _state.get("token"):
        return _state["token"]
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='lan_token'").fetchone()
        tok = row[0] if row and row[0] else secrets.token_urlsafe(32)
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('lan_token', ?)", (tok,))
    _state["token"] = tok
    return tok


def token_ok(value):
    return bool(value) and secrets.compare_digest(value, lan_token())


def reset_token():
    tok = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('lan_token', ?)", (tok,))
    _state["token"] = tok
    _state["pair_code"] = secrets.token_hex(4)


def status():
    running = _state["server"] is not None
    return {"running": running, "ip": _state["ip"], "port": _state["port"],
            "url": pair_url() if running else "", "home": f"http://{_state['ip']}:{_state['port']}/" if running else ""}


def pair_url():
    return f"http://{_state['ip']}:{_state['port']}/pair?code={_state['pair_code']}"


def allowed_hosts():
    if not _state["server"]:
        return ()
    return (f"{_state['ip']}:{_state['port']}",)


def start(handler_cls, port=0, ip=""):
    """在局域网地址上起服务，返回状态。默认用固定端口 27415，被占用就换一个；ip 不填时自动选。"""
    from http.server import ThreadingHTTPServer

    with _lock:
        if _state["server"]:
            return status()
        ip = ip or local_ip()
        if ip.startswith("127.") or not _private(ip):
            raise ValueError("没有找到可用的局域网地址（需要连着 Wi-Fi 或网线）")
        srv = None
        for p in ([port] if port else []) + [27415, 0]:
            try:
                srv = ThreadingHTTPServer((ip, p), handler_cls)
                break
            except OSError:
                continue
        if srv is None:
            raise ValueError("开不了局域网端口")
        srv.daemon_threads = True
        srv.lan = True
        srv.extra_hosts = (f"{ip}:{srv.server_address[1]}",)
        t = threading.Thread(target=srv.serve_forever, name="lan", daemon=True)
        t.start()
        _state.update(server=srv, thread=t, port=srv.server_address[1], ip=ip, pair_code=secrets.token_hex(4))
        lan_token()
        return status()


def stop():
    with _lock:
        srv = _state["server"]
        if srv:
            srv.shutdown()
            srv.server_close()
        _state.update(server=None, thread=None, port=0, ip="", pair_code="")
    return status()


def check_pair(code):
    return bool(_state["server"]) and bool(code) and secrets.compare_digest(code, _state["pair_code"])


def qr_svg(text):
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    return img.to_string(encoding="unicode")
