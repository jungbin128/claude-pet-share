"""PNG 스킨 로더. 단일 sprite.png 또는 같은 크기의 상태별 애니메이션 프레임을 지원한다.

로봇과 같은 GW/GH, draw, center, bulb_center 인터페이스를 제공한다.
애니메이션 캔버스와 광원 좌표는 유지하고 단조 시계로 프레임을 선택한다.
선택 효과는 effects.fire_rings로 켠다. 형식과 상태 목록은 skins/README.md 참고.
"""
import json
import os
import re
from collections import Counter

import fire_rings
import pixel_finish

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
SKIN_DIR = os.path.join(BASE, "skins")
PAD_X, PAD_TOP, PAD_BOT = 6, 10, 2   # 별·느낌표·통통 뛰기 여유 (칸)
LIGHTS = {"idle": (255, 170, 70), "working": (90, 200, 255), "waiting": (255, 200, 60), "done": (100, 230, 140)}


def list_skins():
    """skins 폴더 안 그림 펫 목록 [(폴더 이름, 보이는 이름)]."""
    out = []
    try:
        for name in sorted(os.listdir(SKIN_DIR)):
            if any(os.path.exists(os.path.join(SKIN_DIR, name, f)) for f in ("sprite.png", "idle_0.png")):
                out.append((name, _read_conf(name).get("name") or name))
    except OSError:
        pass
    return out


def _read_conf(name):
    try:
        with open(os.path.join(SKIN_DIR, name, "skin.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _cell_size(img):
    """크게 확대된 도트 그림의 한 칸 크기 (가로·세로 같은 색이 이어지는 길이의 대표값)."""
    px = img.load()
    w, h = img.size
    runs = Counter()
    for y in range(0, h, max(1, h // 60)):
        prev, n = None, 0
        for x in range(w):
            p = px[x, y]
            if p == prev:
                n += 1
            else:
                if prev is not None and prev[3] > 0 and 2 <= n <= w // 8:
                    runs[n] += 1
                prev, n = p, 1
    if not runs:
        return 1.0
    # 한 칸 = 자주 나오는 길이 중 가장 짧은 것 (2칸·3칸 길이는 그 배수). 확대 배율이 정수가 아니면
    # 9·10 처럼 이웃한 두 길이로 섞여 나오므로 ±1 을 묶어 센다.
    total = sum(runs.values())
    for k in sorted(runs):
        group = {j: runs[j] for j in (k, k + 1) if j in runs}
        if sum(group.values()) >= 0.12 * total:
            c = sum(j * v for j, v in group.items()) / sum(group.values())
            return c if c >= 2 else 1.0
    return 1.0


def _clear_background(img):
    """네 귀퉁이가 같은 단색이면 그 색으로 이어진 바깥을 투명하게."""
    w, h = img.size
    corners = [img.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    if any(c[3] < 255 for c in corners) or len({c[:3] for c in corners}) != 1:
        return img
    bg = corners[0][:3]
    rgb = img.convert("RGB")
    mark = (1, 2, 3)
    if bg == mark:
        mark = (4, 5, 6)
    for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        ImageDraw.floodfill(rgb, p, mark, thresh=24)
    keep = ImageChops.difference(rgb, Image.new("RGB", (w, h), mark)).convert("L").point(lambda v: 255 if v else 0)
    out = img.copy()
    out.putalpha(ImageChops.multiply(img.getchannel("A"), keep))
    return out


def _find_light(img):
    """가장 밝고 따뜻한(노랑·주황) 픽셀들의 중심 (없으면 None)."""
    px = img.load()
    w, h = img.size
    pts = []
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a > 200 and r > 220 and g > 170 and b < 120:
                pts.append((x, y))
    if len(pts) < 3:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


GROUPS = ("idle", "working", "waiting", "hover", "celebrate")
TICK_HZ = 12   # pet.pyw 가 넘기는 tick 은 1초에 12씩 늘어남


def _frame_files(folder):
    """장면별 프레임 파일 {장면: [경로...]} + blink 경로. 없으면 sprite.png 한 장을 idle 로."""
    groups = {}
    for g in GROUPS:
        numbered = []
        for filename in os.listdir(folder):
            match = re.fullmatch(re.escape(g) + r"_(\d+)\.png", filename)
            if match:
                numbered.append((int(match.group(1)), os.path.join(folder, filename)))
        files = [path for _, path in sorted(numbered)]
        if files:
            groups[g] = files
    if "idle" not in groups and os.path.exists(os.path.join(folder, "sprite.png")):
        groups["idle"] = [os.path.join(folder, "sprite.png")]
    blink = os.path.join(folder, "blink.png")
    return groups, (blink if os.path.exists(blink) else None)


def _shrink(src, box, cell):
    """box 영역을 잘라 칸 가운데 픽셀로 원래 도트 크기로 줄인다 (번지지 않게)."""
    src = src.crop(box)
    gw, gh = max(1, round(src.width / cell)), max(1, round(src.height / cell))
    small = Image.new("RGBA", (gw, gh), (0, 0, 0, 0))
    sp, dp = src.load(), small.load()
    for y in range(gh):
        for x in range(gw):
            p = sp[min(src.width - 1, int((x + 0.5) * src.width / gw)), min(src.height - 1, int((y + 0.5) * src.height / gh))]
            dp[x, y] = p if p[3] > 128 else (0, 0, 0, 0)
    return small


class ImageSkin:
    """그림(한 장 또는 장면별 여러 장)으로 만든 펫 (pixelpet 모듈과 같은 쓰임새).

    파일: sprite.png 한 장, 또는 idle_0.png… / blink.png / working_ / waiting_ / hover_ / celebrate_ 프레임들
    (docs/PET_ART_REQUEST.md). 여러 장이면 ANIMATED = True 로 pet.pyw 가 단조 시계 기반 frame 토큰을 넘긴다."""

    def __init__(self, name):
        self.name = name
        folder = os.path.join(SKIN_DIR, name)
        conf = _read_conf(name)
        self.pixel_density = float(conf.get("pixel_density", 1.0))
        if not 0.25 <= self.pixel_density <= 4.0:
            raise ValueError("pixel_density must be between 0.25 and 4")
        self.render_scale = 1.0 / self.pixel_density
        self.fire_rings = bool((conf.get("effects") or {}).get("fire_rings"))
        self.flame_shadow = bool((conf.get("effects") or {}).get("flame_shadow"))
        self._flame_shadows = {}
        self.nameplate = conf.get("nameplate")
        self.nameplate_bitmap = None
        if self.nameplate and self.nameplate.get("bitmap") == "assets/fonts/mung_morning_label.png":
            with Image.open(os.path.join(BASE, "assets", "fonts", "mung_morning_label.png")) as bitmap:
                self.nameplate_bitmap = bitmap.convert("L")
        groups, blink = _frame_files(folder)
        if "idle" not in groups:
            raise FileNotFoundError(f"{folder}: sprite.png 또는 idle_0.png 가 없음")
        raw = {g: [_clear_background(Image.open(p).convert("RGBA")) for p in files] for g, files in groups.items()}
        raw_blink = _clear_background(Image.open(blink).convert("RGBA")) if blink else None
        first = raw["idle"][0]
        # Animation atlases already carry a shared registration canvas.
        # Keep it intact so feet and glow coordinates stay fixed across frames.
        allf = [f for fs in raw.values() for f in fs] + ([raw_blink] if raw_blink else [])
        preserve = bool(conf.get("preserve_canvas", sum(len(fs) for fs in raw.values()) > 1))
        if preserve and any(f.size != first.size for f in allf):
            raise ValueError("All animation frames must have the same canvas size")
        self.preserve_canvas = preserve
        boxes = [f.getbbox() for f in allf if f.size == first.size and f.getbbox()]
        if preserve or not boxes:
            box = (0, 0, first.width, first.height)
        else:
            box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                   max(b[2] for b in boxes), max(b[3] for b in boxes))
        self.source_box = box
        # 작은 그림(128픽셀 이하)은 이미 1픽셀 = 도트 1칸으로 보고 줄이지 않는다
        small_art = max(first.size) <= 128
        cell = float(conf.get("cell") or (1.0 if small_art else _cell_size(first.crop(box))))
        flip = bool(conf.get("flip"))
        self._cell = cell
        self.flip = flip

        def prep(img):
            out = _shrink(img if img.size == first.size else img.resize(first.size, Image.NEAREST), box, cell)
            light = conf.get("light")
            if light:
                light = ((light[0] - box[0]) / cell, (light[1] - box[1]) / cell)
            out = pixel_finish.apply(out, conf.get("render_style"), light)
            return out.transpose(Image.FLIP_LEFT_RIGHT) if flip else out

        self.frames = {g: [prep(f) for f in fs] for g, fs in raw.items()}
        self.blink = prep(raw_blink) if raw_blink else None
        self.sprite = self.frames["idle"][0]
        self.fps = dict({"idle": 3, "working": 4, "waiting": 3, "hover": 8, "celebrate": 8}, **(conf.get("fps") or {}))
        self.ANIMATED = self.fire_rings or sum(len(v) for v in self.frames.values()) > 1 or self.blink is not None
        gw, gh = self.sprite.size
        if conf.get("light"):
            lx, ly = conf["light"]
            lx, ly = (lx - box[0]) / cell, (ly - box[1]) / cell
            if flip:
                lx = gw - lx
        else:
            found = _find_light(self.sprite)
            lx, ly = found if found else (gw / 2, 0)
        pad_x, pad_top, pad_bot = (round(v * self.pixel_density) for v in (PAD_X, PAD_TOP, PAD_BOT))
        self.GW, self.GH = gw + 2 * pad_x, gh + pad_top + pad_bot
        self.OX, self.OY = pad_x, pad_top
        self.light = (self.OX + lx + 0.5, self.OY + ly + 0.5)
        self.PAL = {"bulb": dict(LIGHTS, **{k: tuple(v) for k, v in (conf.get("light_colors") or {}).items()})}

    def frame_token(self, state, eyes="open", arms="down", badge=False, stars=(), elapsed=0.0):
        """Finite cache token for a frame; elapsed uses the host monotonic clock."""
        if stars or arms == "up_both":
            group = "celebrate"
        elif arms == "up_right" and not badge:
            group = "hover"
        elif state == "waiting" or badge:
            group = "waiting"
        elif state == "working":
            group = "working"
        else:
            group = "idle"
        if group not in self.frames:
            group = "idle"
        if group == "idle" and state == "idle" and eyes == "blink" and self.blink is not None:
            return ("blink", 0)
        fps = float(self.fps.get(group, 4))
        return (group, int(max(0.0, elapsed) * fps) % len(self.frames[group]))

    def effect_token(self, elapsed):
        return int(elapsed * fire_rings.FPS) % fire_rings.PHASES if self.fire_rings else None

    def draw_nameplate(self, image, scale, bob=0, wave=0, frame=None):
        """Draw the label over its baked-in art, honoring per-frame alignment."""
        spec = self.nameplate
        if not spec:
            return
        try:
            x0, y0, x1, y1 = spec["cover"]
            density = self.pixel_density
            wave_offset = round(density) if wave and len(self.frames.get("hover", ())) <= 1 else 0
            frame_group = frame[0] if isinstance(frame, (tuple, list)) and frame else None
            frame_offset = (spec.get("frame_offsets") or {}).get(frame_group, (0, 0))
            frame_x, frame_y = frame_offset
            # cover coordinates are in the original PNG canvas; ImageSkin stores
            # the frame at one sample per `cell`, with the normal padding added.
            bx, by, _, _ = self.source_box
            cell = self._cell
            coords = [
                (self.OX + (x0 + frame_x - bx) / cell + wave_offset) * scale,
                (self.OY + (y0 + frame_y - by) / cell - round(bob * density)) * scale,
                (self.OX + (x1 + frame_x - bx) / cell + wave_offset) * scale,
                (self.OY + (y1 + frame_y - by) / cell - round(bob * density)) * scale,
            ]
            if self.flip:
                width = image.width
                coords[0], coords[2] = width - coords[2], width - coords[0]
            d = ImageDraw.Draw(image)
            border = tuple(spec.get("border", (67, 38, 26))) + (255,)
            fill = tuple(spec.get("fill", (250, 229, 196))) + (255,)
            radius = max(1, round(scale * 2))
            d.rounded_rectangle(tuple(round(v) for v in coords), radius=radius, fill=border)
            inset = max(1, round(float(spec.get("inset", 5)) / cell * scale))
            inner = (round(coords[0] + inset), round(coords[1] + inset),
                     round(coords[2] - inset), round(coords[3] - inset))
            d.rounded_rectangle(inner, radius=max(1, radius - inset // 2), fill=fill)
            # Render Korean glyphs on the same source-pixel grid as the pet,
            # threshold anti-aliasing, then enlarge with nearest-neighbor.
            base_scale = max(0.01, float(scale))
            mask_size = (max(1, round(image.width / base_scale)),
                         max(1, round(image.height / base_scale)))
            mask = Image.new("L", mask_size, 0)
            md = ImageDraw.Draw(mask)
            cx, cy = (coords[0] + coords[2]) / 2, (coords[1] + coords[3]) / 2
            text_color = tuple(spec.get("text_color", (65, 37, 28))) + (255,)
            max_width = max(1, round((inner[2] - inner[0] - 2) / base_scale))
            if self.nameplate_bitmap is not None:
                glyph = self.nameplate_bitmap.copy()
            else:
                font_size = max(7, round(float(spec.get("font_size", 10))))
                font_path = os.path.join(BASE, "assets", "fonts", "Galmuri11.ttf")
                font = ImageFont.truetype(font_path, font_size)
                text = spec.get("text", "")
                text_box = md.textbbox((0, 0), text, font=font)
                while font_size > 6 and text_box[2] - text_box[0] > max_width:
                    font_size -= 1
                    font = ImageFont.truetype(font_path, font_size)
                    text_box = md.textbbox((0, 0), text, font=font)
                glyph = Image.new("L", (max(1, text_box[2] - text_box[0]),
                                         max(1, text_box[3] - text_box[1])), 0)
                ImageDraw.Draw(glyph).text((-text_box[0], -text_box[1]), text, font=font, fill=255)
                threshold = int(spec.get("pixel_threshold", 110))
                glyph = glyph.point(lambda value: 255 if value >= threshold else 0)
            ink_box = glyph.getbbox()
            if ink_box:
                glyph = glyph.crop(ink_box)
                gx = round(cx / base_scale - glyph.width / 2)
                gy = round(cy / base_scale - glyph.height / 2 + float(spec.get("text_offset_y", 0)))
                mask.paste(glyph, (gx, gy))
            if mask.size != image.size:
                mask = mask.resize(image.size, Image.NEAREST)
            text_layer = Image.new("RGBA", image.size, text_color)
            text_layer.putalpha(mask)
            image.alpha_composite(text_layer)
        except (KeyError, TypeError, ValueError, OSError):
            # A missing system font must not prevent the pet itself from rendering.
            return

    def _pick(self, state, eyes, arms, badge, stars, tick, frame=None):
        group, index = frame or self.frame_token(state, eyes, arms, badge, stars, tick / TICK_HZ)
        if group == "blink" and self.blink is not None:
            return self.blink
        seq = self.frames.get(group, self.frames["idle"])
        return seq[int(index) % len(seq)]

    def _flame_shadow(self, spr):
        """Soft offset shadow of only the warm flame near the declared light point."""
        key = id(spr)
        cached = self._flame_shadows.get(key)
        if cached is not None:
            return cached
        lx = self.light[0] - self.OX - 0.5
        ly = self.light[1] - self.OY - 0.5
        mask = Image.new("L", spr.size, 0)
        src, dst = spr.load(), mask.load()
        reach_y = self.pixel_density
        reach_x = self.pixel_density
        for y in range(max(0, int(ly - 13 * reach_y)), min(spr.height, int(ly + 10 * reach_y))):
            for x in range(max(0, int(lx - 8 * reach_x)), min(spr.width, int(lx + 8 * reach_x))):
                r, g, b, a = src[x, y]
                if a and r > 160 and g > 65 and r > b * 1.3:
                    dst[x, y] = min(150, a)
        full_mask = Image.new("L", (self.GW, self.GH), 0)
        full_mask.paste(mask, (self.OX + round(2 * self.pixel_density), self.OY + round(3 * self.pixel_density)))
        shadow = Image.new("RGBA", full_mask.size, (24, 15, 12, 0))
        shadow.putalpha(full_mask.filter(ImageFilter.GaussianBlur(1.35 * self.pixel_density)))
        self._flame_shadows[key] = shadow
        return shadow

    def draw(self, state="idle", eyes="open", arms="down", bob=0, badge=False, stars=(), wave=0, tick=0, frame=None, fx_phase=None, **_):
        density = self.pixel_density
        bob = round(bob * density)
        img = Image.new("RGBA", (self.GW, self.GH), (0, 0, 0, 0))
        spr = self._pick(state, eyes, arms, badge, stars, tick, frame)
        if self.flame_shadow:
            img.alpha_composite(self._flame_shadow(spr), (0, -bob))
        if self.fire_rings:
            phase = fx_phase if fx_phase is not None else int(tick / TICK_HZ * fire_rings.FPS)
            back, front = fire_rings.layers(self.GW, self.GH, self.OX, self.OY,
                                           self.sprite.width, self.sprite.height,
                                           phase, state)
            img.alpha_composite(back, (0, -bob))
        own_motion = len(self.frames.get("hover", ())) > 1   # 손 흔들기 프레임이 있으면 그림을 흔들지 않음
        img.alpha_composite(spr, (self.OX + (round(density) if wave and not own_motion else 0), self.OY - bob))
        if self.fire_rings:
            img.alpha_composite(front, (0, -bob))
        d = ImageDraw.Draw(img)
        if badge:   # 느낌표 (그림 오른쪽 위)
            s = round
            x0, y0 = self.GW - s(11 * density), max(0, self.OY - s(10 * density) - bob)
            d.rectangle([x0, y0, x0 + s(9 * density), y0 + s(12 * density)], fill=(60, 40, 30, 255))
            d.rectangle([x0 + s(density), y0 + s(density), x0 + s(8 * density), y0 + s(11 * density)], fill=(255, 166, 32, 255))
            d.rectangle([x0 + s(4 * density), y0 + s(3 * density), x0 + s(5 * density), y0 + s(7 * density)], fill=(255, 255, 255, 255))
            d.rectangle([x0 + s(4 * density), y0 + s(9 * density), x0 + s(5 * density), y0 + s(10 * density)], fill=(255, 255, 255, 255))
        spots = ((2, 6), (self.GW - 3, 4), (1, self.GH * 0.6), (self.GW - 2, self.GH * 0.65))
        for (x, y), on in zip(spots, stars):
            if on:
                x, y = int(x), int(y)
                for i in (1, 2, 3):
                    i = round(i * density)
                    for p in ((x, y - i), (x, y + i), (x - i, y), (x + i, y)):
                        d.point(p, fill=(255, 214, 64, 255))
                d.point((x, y), fill=(255, 255, 255, 255))
        return img

    def center(self):
        return self.OX + self.sprite.width / 2, self.OY + self.sprite.height * 0.55

    def bulb_center(self):
        return self.light
