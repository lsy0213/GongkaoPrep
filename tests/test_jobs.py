"""后台任务：排队、取消、出错记录。"""

import threading
import time

from gongkao.library import Jobs


def wait(jobs, timeout=5):
    end = time.time() + timeout
    while jobs.status()["running"] and time.time() < end:
        time.sleep(0.02)
    assert not jobs.status()["running"]


def test_queue_runs_in_order():
    jobs = Jobs()
    order = []
    gate = threading.Event()

    def first(j):
        gate.wait(2)
        order.append("a")

    assert jobs.start("A", first) == "started"
    assert jobs.start("B", lambda j: order.append("b")) == "queued"
    assert jobs.start("B", lambda j: order.append("b2")) == ""  # 同名的不重复排队
    assert jobs.status()["queue"] == ["B"]
    gate.set()
    wait(jobs)
    assert order == ["a", "b"]
    assert [h["name"] for h in jobs.status()["history"]] == ["B", "A"]


def test_cancel_stops_at_next_progress():
    jobs = Jobs()
    seen = []

    def long(j):
        for i in range(1000):
            j.progress("步骤", i, 1000)
            seen.append(i)
            try:  # 整理代码里“个别文件出错就跳过”的写法不能把取消吞掉
                time.sleep(0.005)
            except Exception:  # noqa: BLE001
                pass

    jobs.start("长任务", long)
    jobs.start("排队的", lambda j: seen.append("不该运行"))
    time.sleep(0.05)
    assert jobs.cancel()
    wait(jobs)
    st = jobs.status()
    assert st["cancelled"] and not st["error"]
    assert "不该运行" not in seen and len(seen) < 1000
    assert st["queue"] == []


def test_error_recorded():
    jobs = Jobs()

    def bad(j):
        raise RuntimeError("坏文件")

    jobs.start("出错", bad)
    wait(jobs)
    assert jobs.status()["error"] == "坏文件"


def test_api_cancel(client):
    status, r, _ = client.post("/api/jobs/cancel", {})
    assert status == 200 and r["ok"]
