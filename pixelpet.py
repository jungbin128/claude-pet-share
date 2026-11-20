"""레트로 픽셀아트 펫 (고운 격자 68×76 칸에 찍고, 나중에 정수배로 키움).

모양마다 마스크를 만들고, 마스크를 왼쪽 위/오른쪽 아래로 밀어 빼는 방식으로
가장자리 쪽 칸만 밝게(위·왼쪽) 또는 어둡게(아래·오른쪽) 칠해 입체감을 낸다.
실루엣 바깥 1칸은 진한 남색 테두리.
"""
from PIL import Image, ImageChops, ImageDraw, ImageFilter

GW, GH = 68, 76
OX, OY = 4, 8          # 펫을 격자 안에서 띄우는 여백 (별 · 느낌표 자리)

PAL = {
    # 몸: Claude 주황 (#D97757 계열)
    "outline": (96, 40, 20), "base": (240, 144, 106), "light": (255, 178, 142), "hi": (255, 228, 210),
    "shade": (214, 112, 78), "deep": (172, 80, 50),
    "screen": (30, 20, 18), "bezel": (92, 44, 28), "glare": (66, 42, 34),
    "blush": (255, 150, 160), "white": (255, 255, 255), "star": (255, 214, 64),
    "eye": {"idle": (210, 228, 255), "working": (90, 225, 255), "waiting": (255, 196, 64), "done": (90, 236, 140)},
    "bulb": {"idle": (196, 132, 104), "working": (90, 225, 255), "waiting": (255, 176, 40), "done": (80, 230, 130)},
    "badge": (255, 166, 32),
}


def _shift(m, dx, dy):
    return ImageChops.offset(m, dx, dy)


def _paint(img, mask, color):
    layer = Image.new("RGBA", img.size, tuple(color[:3]) + (255,))
    img.paste(layer, (0, 0), mask)


def _part(img, sil, kind, box, radius, base, light, shade, edge=(2, 2)):
    """둥근 사각형/타원 부위를 명암 넣어 칠하고 실루엣에 더한다."""
    m = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(m)
    x0, y0, x1, y1 = box
    b = [x0 + OX, y0 + OY, x1 + OX, y1 + OY]
    if kind == "oval":
        d.ellipse(b, fill=255)
    else:
        d.rounded_rectangle(b, radius=radius, fill=255)
    _paint(img, m, base)
    ex, ey = edge
    if light:
        _paint(img, ImageChops.subtract(m, _shift(m, ex, ey)), light)
    if shade:
        _paint(img, ImageChops.subtract(m, _shift(m, -ex, -ey)), shade)
    sil.paste(255, (0, 0), m)
    return m


def _px(d, pts, c):
    for x, y in pts:
        d.point((x + OX, y + OY), fill=tuple(c[:3]) + (255,))


def _rect(d, x0, y0, x1, y1, c):
    d.rectangle([x0 + OX, y0 + OY, x1 + OX, y1 + OY], fill=tuple(c[:3]) + (255,))


def draw(state="idle", eyes="open", arms="down", bob=0, badge=False, stars=(), wave=0):
    """작은 RGBA 픽셀 이미지. eyes: open/blink/happy/wide, arms: down/up_right/up_both. bob 은 고운 칸 단위."""
    img = Image.new("RGBA", (GW, GH), (0, 0, 0, 0))
    sil = Image.new("L", (GW, GH), 0)
    oy = -bob
    P = PAL
    # 다리
    for x0 in (14, 36):
        _part(img, sil, "rect", (x0, 51 + oy, x0 + 9, 57 + oy), 2, P["shade"], P["base"], P["deep"], (1, 1))
    # 팔
    arm_l = (0, 30, 5, 41)
    arm_r = (54, 30, 59, 41)
    w2 = wave * 2
    if arms in ("up_right", "up_both"):
        arm_r = (54, 16 + w2, 59, 27 + w2)
    if arms == "up_both":
        arm_l = (0, 16 - w2, 5, 27 - w2)
    for x0, y0, x1, y1 in (arm_l, arm_r):
        _part(img, sil, "rect", (x0, y0 + oy, x1, y1 + oy), 2, P["base"], P["light"], P["shade"], (1, 2))
    # 안테나
    _part(img, sil, "rect", (29, 9 + oy, 30, 16 + oy), 0, P["deep"], None, None)
    bulb = P["bulb"][state]
    _part(img, sil, "oval", (26, 2 + oy, 33, 9 + oy), 0, bulb, None, None)
    d = ImageDraw.Draw(img)
    _px(d, [(28, 4 + oy), (29, 4 + oy), (28, 5 + oy)], P["white"])
    # 몸
    body = _part(img, sil, "rect", (8, 16 + oy, 51, 51 + oy), 8, P["base"], P["light"], P["shade"], (2, 3))
    _paint(img, ImageChops.subtract(body, _shift(body, 0, -1)), P["deep"])     # 맨 아랫줄
    _px(d, [(14, 18 + oy), (15, 18 + oy), (16, 18 + oy), (17, 18 + oy), (12, 19 + oy), (13, 19 + oy),
            (11, 21 + oy), (11, 22 + oy)], P["hi"])
    # 화면: 베젤 → 화면 → 반사
    bz = Image.new("L", img.size, 0)
    ImageDraw.Draw(bz).rounded_rectangle([13 + OX, 21 + oy + OY, 46 + OX, 44 + oy + OY], radius=5, fill=255)
    _paint(img, bz, P["bezel"])
    sc = Image.new("L", img.size, 0)
    ImageDraw.Draw(sc).rounded_rectangle([15 + OX, 23 + oy + OY, 44 + OX, 42 + oy + OY], radius=4, fill=255)
    _paint(img, sc, P["screen"])
    _px(d, [(18, 26 + oy), (19, 26 + oy), (20, 26 + oy), (18, 27 + oy), (18, 28 + oy)], P["glare"])
    # 볼
    for x in (18, 38):
        _rect(d, x, 38 + oy, x + 3, 39 + oy, P["blush"])
    # 눈 · 입
    e = P["eye"][state]
    if eyes == "happy":
        for x in (20, 34):
            _px(d, [(x, 33 + oy), (x + 1, 32 + oy), (x + 2, 31 + oy), (x + 3, 31 + oy), (x + 4, 32 + oy),
                    (x + 5, 33 + oy), (x + 1, 33 + oy), (x + 4, 33 + oy)], e)
        _px(d, [(27, 36 + oy), (28, 37 + oy), (29, 37 + oy), (30, 37 + oy), (31, 37 + oy), (32, 36 + oy)], e)
    elif eyes == "wide":
        for x in (20, 34):
            _rect(d, x + 1, 28 + oy, x + 4, 33 + oy, e)
            _rect(d, x, 29 + oy, x + 5, 32 + oy, e)
            _px(d, [(x + 1, 29 + oy), (x + 2, 29 + oy), (x + 1, 30 + oy)], P["white"])
        _rect(d, 28, 36 + oy, 31, 38 + oy, e)
    elif eyes == "blink":
        for x in (21, 35):
            _rect(d, x, 32 + oy, x + 3, 33 + oy, e)
    else:
        for x in (21, 35):
            _rect(d, x, 28 + oy, x + 3, 33 + oy, e)
            _px(d, [(x, 28 + oy), (x + 1, 28 + oy), (x, 29 + oy)], P["white"])
    # 바깥 테두리 (실루엣을 1칸 넓힌 것 - 실루엣)
    edge = ImageChops.subtract(sil.filter(ImageFilter.MaxFilter(3)), sil)
    ol = Image.new("RGBA", (GW, GH), P["outline"] + (255,))
    ol.putalpha(edge)
    out = Image.alpha_composite(ol, img)
    d2 = ImageDraw.Draw(out)
    if badge:  # 느낌표 말풍선
        _rect(d2, 52, -6 + oy, 61, 6 + oy, P["outline"])
        _rect(d2, 53, -5 + oy, 60, 5 + oy, P["badge"])
        _rect(d2, 56, -3 + oy, 57, 1 + oy, P["white"])
        _rect(d2, 56, 3 + oy, 57, 4 + oy, P["white"])
    for (x, y), on in zip(((-1, 12), (60, 4), (-2, 46), (62, 40)), stars):
        if on:
            _px(d2, [(x, y - 3), (x, y - 2), (x, y - 1), (x, y + 1), (x, y + 2), (x, y + 3),
                     (x - 3, y), (x - 2, y), (x - 1, y), (x + 1, y), (x + 2, y), (x + 3, y)], P["star"])
            _px(d2, [(x, y)], P["white"])
    return out


def center():
    """격자에서 몸통 중심 (칸)."""
    return OX + 30, OY + 34


def bulb_center():
    return OX + 29.5, OY + 5.5
