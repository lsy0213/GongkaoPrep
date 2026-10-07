"""打包后的 exe 冒烟测试（build.bat 打包后自动跑）：用临时数据目录以 --serve 模式启动 dist 里的 exe，
请求几个依赖第三方库的接口（职位表 Excel、闪卡 FSRS、统计、二维码等），确认库都打进去了、日志里没有报错。

    python tools/smoke_exe.py [exe 路径]
"""

import http.client
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
PORT = 27342


def main():
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "GongkaoPrep" / "GongkaoPrep.exe"
    os.environ["GONGKAO_DATA_DIR"] = tempfile.mkdtemp()  # 导入测试用的生成函数时不碰本机数据
    from test_positions import sample

    tmp = tempfile.mkdtemp(prefix="gk-exe-")
    env = dict(os.environ, GONGKAO_DATA_DIR=tmp, GONGKAO_PORT=str(PORT), GONGKAO_NO_AUTOBUILD="1")
    proc = subprocess.Popen([str(exe), "--serve"], env=env)
    host = {"Host": f"127.0.0.1:{PORT}"}
    failures = []
    try:
        cookie, t0 = "", time.time()
        while time.time() - t0 < 60 and not cookie:
            try:
                c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=2)
                c.request("GET", "/", headers=host)
                r = c.getresponse()
                r.read()
                cookie = (r.getheader("Set-Cookie") or "").split(";")[0]
            except OSError:
                time.sleep(0.3)
        if not cookie:
            print("exe 没有启动起来")
            return 1
        print(f"启动用时 {time.time() - t0:.1f} 秒")

        def call(method, path, body=None, ctype="application/json"):
            c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
            h = dict(host, Cookie=cookie)
            if body is not None:
                h["Content-Type"] = ctype
            c.request(method, path, body=body, headers=h)
            r = c.getresponse()
            data = r.read()
            if r.status != 200:
                failures.append(f"{method} {path} → {r.status} {data[:200]!r}")
            return data

        call("GET", "/api/settings")
        call("GET", "/api/dashboard")
        call("GET", "/api/stats")
        call("GET", "/api/analysis")
        call("GET", "/api/storage")
        call("GET", "/api/lan/status")
        call("POST", "/api/cards/preview", json.dumps({"ids": ["x"]}))
        call("POST", "/api/positions/upload?file=t.xlsx", sample(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
    log = Path(tmp) / "logs" / "app.log"
    if log.exists():
        errors = [line for line in log.read_text(encoding="utf-8").splitlines() if " ERROR " in line or " CRITICAL " in line]
        failures += [f"日志：{e}" for e in errors]
    for f in failures:
        print("失败：", f)
    print("exe 冒烟测试", "通过" if not failures else f"有 {len(failures)} 个问题")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
