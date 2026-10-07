"""选岗接口：上传职位表、报名人数表，按个人条件筛岗位。个人条件和收藏的岗位存在界面偏好（prefs）里。"""

import json
from urllib.parse import unquote

from .. import positions
from . import route


def _pref(conn, key, default):
    row = conn.execute("SELECT value FROM prefs WHERE key=?", (key,)).fetchone()
    try:
        return json.loads(row["value"]) if row else default
    except ValueError:
        return default


@route("POST", "/api/positions/upload", write=False)
def upload(ctx):
    name = unquote(ctx.q("file") or "职位表.xlsx")
    return positions.import_positions(ctx.body["_bytes"], name, unquote(ctx.q("name") or ""))


@route("POST", "/api/positions/applicants", write=False)
def applicants(ctx):
    name = unquote(ctx.q("file") or "报名人数.xlsx")
    return positions.import_applicants(ctx.body["_bytes"], name, int(ctx.q("batch") or 0))


@route("POST", "/api/positions/search", write=False)
def search(ctx):
    prof = _pref(ctx.conn, "job_profile", {})
    favs = [str(x) for x in _pref(ctx.conn, "job_favs", [])]
    return positions.search({**ctx.body, "favs": favs}, prof if ctx.body.get("mine") or prof else None)


@route("POST", "/api/positions/delete", write=False)
def delete(ctx):
    positions.delete_batch(int(ctx.body["batch"]))
    return {"ok": True}
