"""接口路由表：各模块用 @route 登记处理函数，server.py 按 (方法, 路径) 查表分发。

处理函数签名 fn(ctx) -> dict | list | None，返回 None 表示“接口不存在”。
写接口（POST，以及少数会顺手写库的 GET）在 userdb.write_lock 下执行；只读的 GET 不加锁，可以并发。
"""

from ..userdb import today_str

ROUTES = {}


def route(method, path, write=None):
    """登记接口。write 不填时：POST 算写，GET 算读。"""

    def deco(fn):
        key = (method, path)
        if key in ROUTES:
            raise RuntimeError(f"接口重复登记：{method} {path}")
        ROUTES[key] = (fn, method == "POST" if write is None else write)
        return fn

    return deco


class Ctx:
    """一次请求的上下文：数据库连接、查询参数、请求体。"""

    def __init__(self, conn, query, body, handler=None):
        self.conn = conn
        self.query = query or {}
        self.body = body or {}
        self.day = today_str()
        self.handler = handler

    def q(self, key, default=None):
        return (self.query.get(key) or [default])[0]


def find(method, path):
    return ROUTES.get((method, path))


def load_all():
    """导入所有接口模块（导入时完成登记）。"""
    from . import home, notes, practice, reading, system  # noqa: F401
