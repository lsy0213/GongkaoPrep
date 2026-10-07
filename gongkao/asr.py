"""本机语音转文字（可选）：面试录音转成文字，算语速、数口头禅，也可以把转写稿交给 AI 点评。

需要自己装 faster-whisper（pip install faster-whisper）并准备模型：
在「设置 → 面试录音」里填模型名（如 small，第一次使用时由 faster-whisper 自动下载约 500 MB）
或本机模型文件夹路径。没装、没填时这个功能不出现，录音、回放和停顿分析照常可用。
"""

import threading

_model = None
_model_key = None
_lock = threading.Lock()


def _setting(conn):
    row = conn.execute("SELECT value FROM settings WHERE key='asr_model'").fetchone()
    return (row[0] if row else "") or ""


def installed():
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def status(conn):
    ok = installed()
    model = _setting(conn)
    return {"installed": ok, "model": model, "ready": ok and bool(model),
            "hint": "" if ok else "装上 faster-whisper（pip install faster-whisper）后可以把录音转成文字"}


def transcribe(path, conn):
    if not installed():
        raise ValueError("还没有安装 faster-whisper：在命令行运行 pip install faster-whisper，然后重启软件")
    model_name = _setting(conn)
    if not model_name:
        raise ValueError("请先在「设置 → 面试录音」里填写语音识别模型（例如 small）")
    global _model, _model_key
    with _lock:
        if _model is None or _model_key != model_name:
            from faster_whisper import WhisperModel

            _model = WhisperModel(model_name, device="auto", compute_type="int8")
            _model_key = model_name
        segments, _info = _model.transcribe(str(path), language="zh", vad_filter=True,
                                            initial_prompt="以下是公务员结构化面试的口头作答，使用简体中文。")
        return "".join(s.text for s in segments).strip()
