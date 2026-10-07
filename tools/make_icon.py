"""生成应用图标：酒红印章底，象牙色摊开的书 + 上方一颗四角星（文曲星），与侧栏标志一致。

    python tools/make_icon.py   # 输出 assets/icon.png、assets/icon.ico 和 web/logo.svg
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"
SIZE = 512
SS = 4  # 先放大画再缩小，边缘更平滑
PAPER = (243, 238, 229)
WINE = (138, 34, 50)


def star(cx, cy, r_out, r_in):
    pts = []
    for i in range(8):
        r = r_out if i % 2 == 0 else r_in
        a = -math.pi / 2 + i * math.pi / 4
        pts.append((round(cx + r * math.cos(a), 1), round(cy + r * math.sin(a), 1)))
    return pts


# 图形都在 512×512 坐标系里，PNG 和 SVG 共用
FRAME = (58, 58, SIZE - 58, SIZE - 58)
COVER = [(96, 246), (96, 392), (256, 424), (416, 392), (416, 246), (256, 278)]
LEFT_PAGE = [(246, 256), (112, 228), (112, 368), (246, 398)]
RIGHT_PAGE = [(266, 256), (400, 228), (400, 368), (266, 398)]
STAR = star(256, 148, 60, 15)


def svg():
    poly = lambda pts, extra="": f'<polygon points="{" ".join(f"{x:g},{y:g}" for x, y in pts)}"{extra}/>'
    paper = "#%02X%02X%02X" % PAPER
    wine = "#%02X%02X%02X" % WINE
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}">',
        f'<rect x="16" y="16" width="{SIZE - 32}" height="{SIZE - 32}" rx="36" fill="{wine}"/>',
        f'<rect x="{FRAME[0]}" y="{FRAME[1]}" width="{FRAME[2] - FRAME[0]}" height="{FRAME[3] - FRAME[1]}" fill="none" stroke="{paper}" stroke-opacity=".6" stroke-width="6"/>',
        f'<g fill="{paper}">',
        poly(COVER, ' fill-opacity=".5"'),
        poly(LEFT_PAGE),
        poly(RIGHT_PAGE),
        poly(STAR),
        "</g>",
        "</svg>",
        "",
    ])


def main():
    OUT.mkdir(exist_ok=True)
    big = SIZE * SS
    s = lambda pts: [(x * SS, y * SS) for x, y in pts]
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([16 * SS, 16 * SS, big - 16 * SS, big - 16 * SS], radius=36 * SS, fill=WINE)
    d.rectangle([c * SS for c in FRAME], outline=PAPER, width=6 * SS)
    cover = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(cover).polygon(s(COVER), fill=PAPER + (128,))
    img.alpha_composite(cover)
    d = ImageDraw.Draw(img)
    for pts in (LEFT_PAGE, RIGHT_PAGE, STAR):
        d.polygon(s(pts), fill=PAPER)
    img = img.resize((SIZE, SIZE), Image.LANCZOS)
    img.save(OUT / "icon.png")
    img.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    (ROOT / "web" / "logo.svg").write_text(svg(), encoding="utf-8")
    print("已生成", OUT / "icon.png", OUT / "icon.ico", ROOT / "web" / "logo.svg")


if __name__ == "__main__":
    main()
