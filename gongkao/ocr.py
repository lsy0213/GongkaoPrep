"""扫描版 PDF 的文字识别（RapidOCR / PaddleOCR 模型，离线运行）。

有显卡时用 DirectML 加速（约 1.3 秒一页，纯 CPU 约 10 秒）。识别结果由调用方按页缓存，
同一页只识别一次。
"""

import threading

ZOOM = 2.0  # 渲染倍数：A4 横版约 1680×1190 像素，小字也能认清

_engine = None
_lock = threading.Lock()


def available():
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def engine():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            try:
                import onnxruntime

                dml = "DmlExecutionProvider" in onnxruntime.get_available_providers()
            except Exception:  # noqa: BLE001
                dml = False
            kw = {"det_use_dml": True, "cls_use_dml": True, "rec_use_dml": True} if dml else {}
            _engine = RapidOCR(**kw)
        return _engine


def page_zoom(page):
    """整页识别用的渲染倍数：一般页面 ZOOM；特别大的页面（扫描成 2381×3367 这种）缩到不用切块，
    否则一行字比切块还宽，每块里都是半行，被当成切断的字丢掉，行中间整段漏认。"""
    w, h = page.rect.width or 1, page.rect.height or 1
    if max(w, h) > min(w, h) * 3:
        # 拼成一整页的长图（1191×20205 的月度汇总）：按短边定倍数、切块认；按长边缩会缩成看不清的细条
        return min(ZOOM, TILE * 0.9 / min(w, h))
    return min(ZOOM, TILE * 1.75 / max(w, h))


def page_image(page, zoom=ZOOM):
    import numpy as np
    import pymupdf

    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    return img[:, :, :3].copy()


def recognize_clip(page, rect, zoom=ZOOM):
    """只识别页面上的一块区域（文字版 PDF 里嵌着图片的单元格），返回值同 recognize。"""
    import numpy as np
    import pymupdf

    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=pymupdf.Rect(rect), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3].copy()
    return [(b[0] + rect[0], b[1] + rect[1], b[2] + rect[0], b[3] + rect[1], b[4], b[5])
            for b in recognize(img, zoom)]


def sideways(boxes):
    """识别结果里多数文字块是竖条：整页横着放（横版的表、导图扫描成竖版）。"""
    long = [b for b in boxes if len(b[4]) >= 3]
    tall = sum(1 for b in long if (b[3] - b[1]) > (b[2] - b[0]) * 1.5)
    return len(long) >= 6 and tall >= len(long) * 0.5


def recognize_upright(img, zoom=ZOOM, gaps=True):
    """同 recognize；整页横着放时转正再识别（顺时针、逆时针各试一次，取识别得好的）。
    转正后的坐标是转正后图片上的坐标。gaps=True 时再补认漏掉的行（见 fill_gaps）。"""
    import numpy as np

    boxes = recognize(img, zoom)
    if sideways(boxes):
        best = None
        for k in (1, 3):
            im = np.ascontiguousarray(np.rot90(img, k))
            bs = recognize(im, zoom)
            good = [b for b in bs if b[5] >= 0.8 and (b[3] - b[1]) < (b[2] - b[0]) * 1.5]
            score = sum(len(b[4]) * b[5] for b in good)
            if best is None or score > best[0]:
                best = (score, bs, im)
        boxes, img = best[1], best[2]
    if gaps:
        boxes = boxes + fill_gaps(img, boxes, zoom)
    return boxes


def fill_gaps(img, boxes, zoom=ZOOM):
    """文字检测偶尔整行漏掉（常是加粗、带颜色的答案行）：找出有墨迹却没有识别结果的横条，单独再认一次。"""
    import numpy as np

    gray = img[:, :, :3].mean(axis=2) if img.ndim == 3 else img
    H, W = gray.shape
    rows = (gray < 150).sum(axis=1)
    cov = np.zeros(H, bool)
    for b in boxes:
        if b[5] >= 0.5:
            cov[max(0, int(b[1] * zoom) - 3): int(b[3] * zoom) + 3] = True
    ink = (rows > max(6, W * 0.004)) & ~cov
    extra = []
    y = 0
    while y < H:
        if not ink[y]:
            y += 1
            continue
        z = y
        while z + 1 < H and (ink[z + 1] or (z + 4 < H and ink[z + 2:z + 5].any())):
            z += 1
        if 10 * zoom / 2 <= z - y <= 90 * zoom / 2:
            a = max(0, y - 8)
            crop = np.ascontiguousarray(img[a: z + 8])
            for b in recognize(crop, zoom):
                extra.append((b[0], round(b[1] + a / zoom, 1), b[2], round(b[3] + a / zoom, 1), b[4], b[5]))
        y = z + 1
    return extra


TILE = 1800  # 超大图（整张长图导图）切块识别，整张缩小再认字会糊
OVERLAP = 600


def recognize(img, zoom=ZOOM):
    """识别一张页面图，返回 [(x0, y0, x1, y1, 文字, 置信度)]（已换算回 PDF 坐标）。"""
    H, W = img.shape[:2]
    if max(H, W) > TILE * 1.8:
        return _recognize_tiles(img, zoom)
    try:
        res, _ = engine()(img)
    except Exception:  # noqa: BLE001 —— 太扁、太小的图片（补认漏行时的细条）缩放失败
        return []
    boxes = []
    for quad, text, score in res or []:
        xs = [p[0] for p in quad]
        ys = [p[1] for p in quad]
        boxes.append((round(min(xs) / zoom, 1), round(min(ys) / zoom, 1), round(max(xs) / zoom, 1),
                      round(max(ys) / zoom, 1), text, round(float(score), 3)))
    return boxes


def _recognize_tiles(img, zoom):
    """切成互相重叠的块逐块识别：碰到块内侧边缘的字是被切断的，丢掉（相邻块里有完整的）；重叠区认了两次的去重。"""
    import numpy as np

    H, W = img.shape[:2]
    step = TILE - OVERLAP
    out = []
    for y in range(0, max(1, H - OVERLAP), step):
        for x in range(0, max(1, W - OVERLAP), step):
            crop = np.ascontiguousarray(img[y: y + TILE, x: x + TILE])
            h, w = crop.shape[:2]
            for b in recognize(crop, 1.0):
                cut = (x > 0 and b[0] <= 4) or (y > 0 and b[1] <= 4) or (x + w < W and b[2] >= w - 4) or (y + h < H and b[3] >= h - 4)
                if cut:
                    continue
                box = (b[0] + x, b[1] + y, b[2] + x, b[3] + y, b[4], b[5])
                if any(_iou(box, o) > 0.4 for o in out):
                    continue
                out.append(box)
    return [(round(b[0] / zoom, 1), round(b[1] / zoom, 1), round(b[2] / zoom, 1), round(b[3] / zoom, 1), b[4], b[5])
            for b in out]


def _iou(a, b):
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0
    inter = ix * iy
    return inter / min((a[2] - a[0]) * (a[3] - a[1]) or 1, (b[2] - b[0]) * (b[3] - b[1]) or 1)
