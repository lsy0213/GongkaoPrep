"""API Key 加密保存：Windows 上用 DPAPI（CryptProtectData），只有当前 Windows 用户在这台电脑上能解开。

数据库里存成 "dpapi:<base64>"；老版本存的明文在启动时自动加密。非 Windows 系统没有 DPAPI，原样保存。
数据目录拷到别的电脑或别的用户下时解不开，读出来是空字符串，需要重新填写 Key。
"""

import base64
import sys

PREFIX = "dpapi:"
_ENTROPY = b"GongkaoPrep/ai_api_key"


def _dpapi():
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    def blob(data):
        buf = ctypes.create_string_buffer(data, len(data))
        return Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def run(fn, data):
        src, _keep = blob(data)
        ent, _keep2 = blob(_ENTROPY)
        out = Blob()
        # CRYPTPROTECT_UI_FORBIDDEN = 0x1
        if not fn(ctypes.byref(src), None, ctypes.byref(ent), None, None, 0x1, ctypes.byref(out)):
            raise OSError("DPAPI 调用失败")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            kernel32.LocalFree(out.pbData)

    return (lambda data: run(crypt32.CryptProtectData, data),
            lambda data: run(crypt32.CryptUnprotectData, data))


def is_protected(stored: str) -> bool:
    return (stored or "").startswith(PREFIX)


def protect(text: str) -> str:
    text = text or ""
    if not text or is_protected(text):
        return text
    api = _dpapi()
    if not api:
        return text
    return PREFIX + base64.b64encode(api[0](text.encode("utf-8"))).decode("ascii")


def unprotect(stored: str) -> str:
    stored = stored or ""
    if not is_protected(stored):
        return stored  # 明文（老数据或非 Windows）
    api = _dpapi()
    if not api:
        return ""
    try:
        return api[1](base64.b64decode(stored[len(PREFIX):])).decode("utf-8")
    except (OSError, ValueError):
        return ""  # 换了电脑或 Windows 用户：解不开，当作没填
