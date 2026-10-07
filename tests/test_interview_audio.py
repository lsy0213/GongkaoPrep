"""面试录音：上传、回放、语音指标；上传接口的访问控制。"""

from gongkao.api.notes import speech_metrics


def test_speech_metrics():
    m = speech_metrics("嗯，我认为这个问题，然后就是要那个加强监管", 60, {"pauses": 2, "longest": 3})
    assert m["cpm"] > 0 and m["pauses"] == 2
    assert m["fillers"]["嗯"] == 1 and m["fillers"]["然后"] == 1 and m["fillers"]["那个"] == 1


def test_upload_and_play(client):
    _s, iv, _ = client.post("/api/interviews", {"qid": "i1", "answer": "要点", "seconds": 150})
    audio = b"\x1aE\xdf\xa3" + b"0" * 2000  # 只是个 webm 文件头 + 填充
    status, r, _ = client.request("POST", f"/api/interviews/audio?id={iv['id']}", body=audio,
                                  headers={"Content-Type": "audio/webm"})
    assert status == 200 and r["audio"] == f"iv-{iv['id']}.webm"
    status, data, hdrs = client.request("GET", f"/api/recording/{r['audio']}", raw=True)
    assert status == 200 and data == audio and hdrs["content-type"] == "audio/webm"
    _s, m, _ = client.post("/api/interviews/metrics", {"id": iv["id"], "pauses": {"pauses": 1, "longest": 4, "speech_seconds": 120},
                                                       "transcript": "我认为然后要加强", "speech_seconds": 120})
    assert m["metrics"]["pauses"] == 1 and m["metrics"]["cpm"] == 4
    _s, lst, _ = client.get("/api/interviews")
    row = next(x for x in lst["items"] if x["id"] == iv["id"])
    assert row["audio"] and "cpm" in row["metrics"]


def test_upload_guarded(client, anon):
    # 普通文本类型（跨站能直接发的“简单请求”）不收
    status, _r, _ = client.request("POST", "/api/interviews/audio?id=1", body=b"x", headers={"Content-Type": "text/plain"})
    assert status == 403
    # 没有会话不收
    status, _r, _ = anon.request("POST", "/api/interviews/audio?id=1", body=b"x", headers={"Content-Type": "audio/webm"})
    assert status == 403
    # 其他接口不收音频类型
    status, _r, _ = client.request("POST", "/api/prefs", body=b"x", headers={"Content-Type": "audio/webm"})
    assert status == 403
    status, _r, _ = client.request("GET", "/api/recording/..%5capp.db", raw=True)
    assert status == 400


def test_asr_status(client):
    _s, st, _ = client.get("/api/asr/status")
    assert "installed" in st and st["ready"] in (True, False)
