# KeyaraMusic — "Editorial Bloom" thumbnail engine (v2)
#
# Floral background + tilted semi-transparent editorial card:
#   1. Background: user ka floral art, har render me naya random crop/flip/tint
#      (different look every time — "animation type" vibe)
#   2. Editorial card: warm off-white paper (semi-transparent — floral peek
#      through), tilted -2.4..2.4 deg, crisp navy border, flat premium look
#   3. Header: kicker block (lime/cobalt, randomised) + big navy duration + deco motif
#   4. Left column: bold navy headline, cobalt channel + badge, meta rule,
#      progress bar (accent fill + opposite-accent knob), flat controls
#   5. Right column: navy "screen" panel with FULL artwork (contain, no crop)
#      + thin offset hairline frame; neeche floral blossom cluster aur
#      drifting petals (har render me naye — animation vibe)
#   6. Footer: brand masthead + navy/cobalt/lime Swiss chips
#
# Har gen_thumb call naya seed use karta hai -> har baar alag look.
# Sirf stdlib + Pillow.

import hashlib
import math
import random
import time
import traceback
from pathlib import Path

import aiofiles
import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from KeyaraMusic import app
from py_yt import VideosSearch

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

CANVAS_W, CANVAS_H = 1320, 760

FONT_REGULAR_PATH = "KeyaraMusic/assets/font2.ttf"
FONT_BOLD_PATH = "KeyaraMusic/assets/font3.ttf"
DEFAULT_THUMB = "KeyaraMusic/assets/ShrutiBots.jpg"
BG_PATH = "KeyaraMusic/assets/thumb_bg.jpg"

# ----- palette (flat, no gradients) ------------------------------------------
PAPER = (247, 243, 233)           # warm off-white
PAPER_A = 175                     # card alpha — floral peek through kare
INK = (16, 28, 62, 255)           # bold navy typography
INK_SOFT = (16, 28, 62, 235)      # navy, secondary weight
INK_FAINT = (16, 28, 62, 90)      # navy, hairline / track
COBALT = (32, 84, 226, 255)       # cobalt blue accent
LIME = (198, 240, 60, 255)        # lime green accent
MAGENTA = (200, 60, 110)          # bg tint option

# ----- grid -------------------------------------------------------------------
M = 64
HEADER_RULE_Y = 112
FOOTER_RULE_Y = 680
COL_SPLIT_X = 732

TITLE_X, TITLE_Y = M, 140
TITLE_W = 620
TITLE_MAX_H = 200
CHANNEL_TOP = 370
META_RULE_Y = 440
TIMES_Y = 470
TRACK_Y = 526
TRACK_H = 10
CTRL_CY = 606

ART_X0, ART_Y0, ART_X1, ART_Y1 = 768, 150, 1256, 638     # 488 x 488 screen
ART_PAD = 16                                               # navy bezel

# ----- floral motif palette (matches the background art) --------------------------
PETAL_COLORS = [
    (214, 92, 132, 255),    # rose
    (196, 64, 108, 255),    # deep pink
    (176, 48, 92, 255),     # wine
    (222, 180, 84, 255),    # gold fleck
]
PETAL_CENTERS = [(222, 180, 84, 255), (247, 243, 233, 255), (176, 48, 92, 255)]

CX = M + TITLE_W // 2


def _rng_for(seed) -> random.Random:
    s = int(hashlib.sha256(str(seed).encode()).hexdigest()[:16], 16)
    return random.Random(s)


def _fmt_time(sec) -> str:
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _parse_seconds(duration):
    if not duration or ":" not in str(duration):
        return None
    try:
        parts = [int(p) for p in str(duration).split(":")]
    except ValueError:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


# ----- primitives --------------------------------------------------------------


def _cover_crop(img, w, h):
    scale = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    x = (img.width - w) // 2
    y = (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def _wrap_lines(draw, text, font, max_w):
    """Greedy word wrap; over-long words hard-split."""
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
            cur = ""
        while len(w) > 1 and draw.textlength(w, font=font) > max_w:
            cut = len(w)
            while cut > 1 and draw.textlength(w[:cut], font=font) > max_w:
                cut -= 1
            lines.append(w[:cut])
            w = w[cut:]
        cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _tracked(draw, x, y, text, font, spacing, fill):
    """Letter-spaced text (Swiss kicker style). Returns total width."""
    cx = x
    for ch in text:
        draw.text((cx, y), ch, font=font, fill=fill)
        cx += draw.textlength(ch, font=font) + spacing
    return cx - x - spacing


def _check_badge(draw, cx, cy, r=12, color=COBALT):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    draw.line([(cx - 5, cy), (cx - 1, cy + 5)], fill=(*PAPER, 255), width=3)
    draw.line([(cx - 1, cy + 5), (cx + 6, cy - 5)], fill=(*PAPER, 255), width=3)


# ----- background: har baar nayi look -------------------------------------------


def _background(rng):
    try:
        base = Image.open(BG_PATH).convert("RGBA")
    except Exception:
        base = Image.new("RGBA", (CANVAS_W, CANVAS_H), (*PAPER, 255))

    # random zoom + crop + optional mirror -> har render alag framing
    zoom = rng.uniform(1.0, 1.22)
    bw, bh = int(CANVAS_W * zoom), int(CANVAS_H * zoom)
    big = _cover_crop(base, bw, bh)
    if rng.random() < 0.5:
        big = ImageOps.mirror(big)
    x = rng.randint(0, bw - CANVAS_W)
    y = rng.randint(0, bh - CANVAS_H)
    canvas = big.crop((x, y, x + CANVAS_W, y + CANVAS_H))

    # random mood tint
    tint, alpha = rng.choice(
        [(None, 0), (COBALT[:3], 26), (LIME[:3], 20), (MAGENTA, 30), (INK[:3], 28)]
    )
    if tint:
        canvas.alpha_composite(Image.new("RGBA", canvas.size, (*tint, alpha)))

    # slight per-render exposure
    canvas = ImageEnhance.Brightness(canvas).enhance(rng.uniform(0.9, 1.08))
    return canvas


# ----- card: header / footer / rules ---------------------------------------------


def _header(card, rng, total, secondary):
    d = ImageDraw.Draw(card)
    # kicker block (secondary accent) — text contrast ke hisaab se
    kfill = secondary
    ktext = (*PAPER, 255) if secondary[:3] == COBALT[:3] else INK
    kfont = ImageFont.truetype(FONT_BOLD_PATH, 18)
    label = "NOW PLAYING"
    lw = 0
    for ch in label:
        lw += d.textlength(ch, font=kfont) + 4
    lw -= 4
    block_w = int(lw) + 44
    d.rectangle([M, 56, M + block_w, 96], fill=kfill, outline=INK, width=2)
    _tracked(d, M + 22, 67, label, kfont, 4, ktext)

    # random deco motif between kicker and duration
    mx = rng.randint(M + block_w + 60, 980)
    my = 76
    motif = rng.randrange(5)
    if motif == 0:
        for i in range(3):
            d.rectangle([mx + i * 20, my - 7, mx + i * 20 + 10, my + 3], fill=secondary)
    elif motif == 1:
        d.ellipse([mx - 13, my - 13, mx + 13, my + 13], outline=INK, width=3)
    elif motif == 2:
        d.line([(mx - 14, my), (mx + 14, my)], fill=INK, width=3)
        d.line([(mx, my - 14), (mx, my + 14)], fill=INK, width=3)
    elif motif == 3:
        for i in range(3):
            d.line([(mx + i * 14, my + 10), (mx + i * 14 + 12, my - 10)], fill=secondary, width=4)
    # motif==4 -> clean (no deco)

    # big duration, right-aligned
    dfont = ImageFont.truetype(FONT_BOLD_PATH, 46)
    txt = _fmt_time(total) if total else "--:--"
    w = d.textlength(txt, font=dfont)
    d.text((CANVAS_W - M - w, 48), txt, font=dfont, fill=INK)

    d.rectangle([M, HEADER_RULE_Y, CANVAS_W - M, HEADER_RULE_Y + 2], fill=INK)


def _footer(card, brand):
    d = ImageDraw.Draw(card)
    d.rectangle([M, FOOTER_RULE_Y, CANVAS_W - M, FOOTER_RULE_Y + 2], fill=INK)

    bfont = ImageFont.truetype(FONT_BOLD_PATH, 26)
    name = brand or "Sitara_MusicBot"
    if not name.startswith("@"):
        name = "@" + name
    d.text((M, FOOTER_RULE_Y + 18), name, font=bfont, fill=INK)

    chip, gap = 22, 12
    y = FOOTER_RULE_Y + 20
    x0 = CANVAS_W - M - (3 * chip + 2 * gap)
    for i, color in enumerate((INK, COBALT, LIME)):
        x = x0 + i * (chip + gap)
        d.rectangle([x, y, x + chip, y + chip], fill=color, outline=INK, width=2)


def _column_rule(card):
    d = ImageDraw.Draw(card)
    d.rectangle([COL_SPLIT_X, 140, COL_SPLIT_X + 2, 650], fill=INK_FAINT)


# ----- left column ------------------------------------------------------------------


def _title(card, text):
    d = ImageDraw.Draw(card)
    text = str(text or "Sitara Music")
    font, lines, lh = None, None, 0
    for size in (74, 66, 58, 50, 44):
        font = ImageFont.truetype(FONT_BOLD_PATH, size)
        lines = _wrap_lines(d, text, font, TITLE_W)
        lh = int(size * 1.1)
        if len(lines) * lh <= TITLE_MAX_H:
            break
    max_lines = max(1, TITLE_MAX_H // lh)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and d.textlength(last + "…", font=font) > TITLE_W:
            last = last[:-1]
        lines[-1] = last + "…"
    y = TITLE_Y
    for ln in lines:
        d.text((TITLE_X, y), ln, font=font, fill=INK)
        y += lh


def _channel(card, channel):
    d = ImageDraw.Draw(card)
    cfont = ImageFont.truetype(FONT_BOLD_PATH, 32)
    txt = str(channel or "Sitara Music")
    max_w = TITLE_W - 48
    full = txt
    while txt and d.textlength(txt, font=cfont) > max_w:
        txt = txt[:-1]
    if txt != full:
        txt = txt.rstrip() + "…"
    d.text((M, CHANNEL_TOP), txt, font=cfont, fill=COBALT)
    w = d.textlength(txt, font=cfont)
    _check_badge(d, int(M + w + 24), CHANNEL_TOP + 20, r=13)


def _progress_and_times(card, progress, total, primary, secondary):
    d = ImageDraw.Draw(card)
    tfont = ImageFont.truetype(FONT_REGULAR_PATH, 24)

    elapsed = _fmt_time(progress * total) if total else "0:00"
    remaining = f"-{_fmt_time(total - progress * total)}" if total else "--:--"
    d.text((M, TIMES_Y), elapsed, font=tfont, fill=INK_SOFT)
    rw = d.textlength(remaining, font=tfont)
    d.text((M + TITLE_W - rw, TIMES_Y), remaining, font=tfont, fill=INK_SOFT)

    d.rectangle([M, TRACK_Y, M + TITLE_W, TRACK_Y + TRACK_H], fill=INK_FAINT)
    fx = M + TITLE_W * progress
    if fx > M + 2:
        d.rectangle([M, TRACK_Y, int(fx), TRACK_Y + TRACK_H], fill=primary)
    kx = int(min(max(fx, M + 10), M + TITLE_W - 10))
    ky = TRACK_Y + TRACK_H // 2 - 9
    d.rectangle([kx - 9, ky, kx + 9, ky + 18], fill=secondary, outline=INK, width=2)


def _glyph_prev(d, cx, cy, color):
    d.rectangle([cx - 11, cy - 11, cx - 6, cy + 11], fill=color)
    d.polygon([(cx + 10, cy - 11), (cx + 10, cy + 11), (cx - 3, cy)], fill=color)


def _glyph_next(d, cx, cy, color):
    d.rectangle([cx + 6, cy - 11, cx + 11, cy + 11], fill=color)
    d.polygon([(cx - 10, cy - 11), (cx - 10, cy + 11), (cx + 3, cy)], fill=color)


def _glyph_shuffle(d, cx, cy, color):
    d.line([(cx - 11, cy - 7), (cx + 10, cy + 7)], fill=color, width=3)
    d.line([(cx - 11, cy + 7), (cx + 10, cy - 7)], fill=color, width=3)
    d.line([(cx - 11, cy - 7), (cx - 11, cy + 2)], fill=color, width=3)
    d.polygon([(cx + 10, cy + 2), (cx + 1, cy + 4), (cx + 7, cy + 11)], fill=color)
    d.polygon([(cx + 10, cy - 2), (cx + 1, cy - 4), (cx + 7, cy - 11)], fill=color)


def _glyph_repeat(d, cx, cy, color):
    bbox = [cx - 12, cy - 9, cx + 12, cy + 9]
    d.arc(bbox, start=-40, end=160, fill=color, width=3)
    d.arc(bbox, start=140, end=320, fill=color, width=3)
    d.polygon([(cx + 11, cy + 2), (cx + 1, cy - 1), (cx + 8, cy + 9)], fill=color)
    d.polygon([(cx - 11, cy - 2), (cx - 1, cy + 1), (cx - 8, cy - 9)], fill=color)


def _controls(card, primary):
    d = ImageDraw.Draw(card)
    r = 42
    tri = (*PAPER, 255) if primary[:3] == COBALT[:3] else INK
    d.ellipse([CX - r, CTRL_CY - r, CX + r, CTRL_CY + r], fill=primary, outline=INK, width=2)
    d.polygon(
        [(CX - 12, CTRL_CY - 18), (CX - 12, CTRL_CY + 18), (CX + 17, CTRL_CY)],
        fill=tri,
    )
    _glyph_prev(d, CX - 120, CTRL_CY, INK)
    _glyph_next(d, CX + 120, CTRL_CY, INK)
    _glyph_shuffle(d, M + 34, CTRL_CY, INK)
    _glyph_repeat(d, M + TITLE_W - 34, CTRL_CY, INK)


# ----- right column: artwork (FULL, contain — kabhi cut nahi) -------------------------


def _art_panel(card, art, rng):
    d = ImageDraw.Draw(card)
    # thin offset registration frame (filled "board" hataya — ab sirf hairline depth)
    off = 14
    dx = off if rng.random() < 0.5 else -off
    dy = off if rng.random() < 0.5 else -off
    d.rectangle(
        [ART_X0 + dx, ART_Y0 + dy, ART_X1 + dx, ART_Y1 + dy],
        outline=INK,
        width=2,
    )

    # navy screen — artwork isi ke andar FULL fit hoti hai (contain, no crop)
    w, h = ART_X1 - ART_X0, ART_Y1 - ART_Y0
    d.rectangle([ART_X0, ART_Y0, ART_X1 - 1, ART_Y1 - 1], fill=INK)

    iw, ih = w - ART_PAD * 2, h - ART_PAD * 2
    scale = min(iw / art.width, ih / art.height)
    aw, ah = max(1, int(art.width * scale)), max(1, int(art.height * scale))
    fitted = art.convert("RGB").resize((aw, ah), Image.LANCZOS)
    card.paste(fitted, (ART_X0 + (w - aw) // 2, ART_Y0 + (h - ah) // 2))

    d.rectangle([ART_X0, ART_Y0, ART_X1 - 1, ART_Y1 - 1], outline=(*PAPER, 255), width=2)
    d.rectangle([ART_X0 - 3, ART_Y0 - 3, ART_X1 + 2, ART_Y1 + 2], outline=INK, width=3)


def _blossom(card, cx, cy, r, petal, center):
    d = ImageDraw.Draw(card)
    for i in range(5):
        a = math.radians(i * 72 - 90)
        px = cx + math.cos(a) * r * 0.62
        py = cy + math.sin(a) * r * 0.62
        d.ellipse([px - r * 0.52, py - r * 0.52, px + r * 0.52, py + r * 0.52], fill=petal)
    d.ellipse([cx - r * 0.34, cy - r * 0.34, cx + r * 0.34, cy + r * 0.34], fill=center)


def _floral_motifs(card, rng):
    """Blossom cluster video ke neeche + drifting petals — fresh every render."""
    # cluster: bottom-left corner of the screen, bahar ki taraf
    n = rng.randint(2, 3)
    cx = ART_X0 + rng.randint(4, 90)
    for _ in range(n):
        r = rng.randint(10, 16)
        cy = rng.randint(650, 666)
        _blossom(card, cx, cy, r, rng.choice(PETAL_COLORS), rng.choice(PETAL_CENTERS))
        cx += rng.randint(r + 12, r + 34)

    # corner blossom: top-right margin, screen ke bahar
    _blossom(
        card,
        rng.randint(1266, 1298),
        rng.randint(118, 152),
        rng.randint(10, 14),
        rng.choice(PETAL_COLORS),
        rng.choice(PETAL_CENTERS),
    )

    # loose drifting petals — sirf safe zones me (video/text/chips ke upar nahi)
    zones = [
        (700, 640, 1300, 676),   # screen aur footer rule ke beech
        (700, 690, 1120, 752),   # footer rule ke neeche, chips ke baayein
        (690, 130, 762, 640),    # columns ka gutter
        (1264, 100, 1306, 660),  # right margin, screen ke baayein
    ]
    d = ImageDraw.Draw(card)
    for _ in range(rng.randint(6, 10)):
        zx0, zy0, zx1, zy1 = rng.choice(zones)
        px = rng.randint(zx0, zx1)
        py = rng.randint(zy0, zy1)
        rw = rng.randint(4, 8)
        rh = int(rw * rng.uniform(1.2, 1.7))
        d.ellipse([px - rw, py - rh, px + rw, py + rh], fill=rng.choice(PETAL_COLORS))


# ----- main ---------------------------------------------------------------------------


def _render(videoid: str, title, channel, total, progress, art, rng=None) -> str:
    if rng is None:
        # har call naya seed -> har baar alag look
        rng = _rng_for(f"{videoid}:{time.time():.0f}")

    primary = COBALT if rng.random() < 0.6 else LIME
    secondary = LIME if primary[:3] == COBALT[:3] else COBALT

    # 1. floral background (fresh framing/tint)
    canvas = _background(rng)

    # 2. semi-transparent editorial card, tilted
    card = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rectangle([0, 0, CANVAS_W - 1, CANVAS_H - 1], fill=(*PAPER, PAPER_A))

    _header(card, rng, total, secondary)
    _title(card, title)
    _channel(card, channel)
    d.rectangle([M, META_RULE_Y, M + TITLE_W, META_RULE_Y + 2], fill=INK)
    _progress_and_times(card, progress, total, primary, secondary)
    _controls(card, primary)
    _column_rule(card)
    _art_panel(card, art, rng)
    _floral_motifs(card, rng)

    try:
        brand = getattr(app, "username", None)
    except Exception:
        brand = None
    _footer(card, brand)

    # crisp navy frame
    d = ImageDraw.Draw(card)
    d.rectangle([2, 2, CANVAS_W - 3, CANVAS_H - 3], outline=INK, width=4)

    angle = rng.uniform(0.9, 2.4) * rng.choice((-1, 1))
    card = card.rotate(angle, resample=Image.BICUBIC)
    canvas.alpha_composite(card)

    out = CACHE_DIR / f"{videoid}_final.png"
    canvas.convert("RGB").save(out, optimize=True)
    return str(out)


async def gen_thumb(videoid: str):
    url = f"https://www.youtube.com/watch?v={videoid}"
    raw_art_path = None
    try:
        results = VideosSearch(url, limit=1)
        result = (await results.next())["result"][0]

        title = result.get("title", "Unknown Title")
        duration = result.get("duration", "Unknown")
        thumburl = result["thumbnails"][0]["url"].split("?")[0]
        channel = result.get("channel", {}).get("name", "Unknown Channel")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(thumburl) as resp:
                    if resp.status == 200:
                        raw_art_path = CACHE_DIR / f"raw_{videoid}.png"
                        async with aiofiles.open(raw_art_path, "wb") as f:
                            await f.write(await resp.read())
        except Exception:
            raw_art_path = None

        if raw_art_path and Path(raw_art_path).exists():
            base_img = Image.open(raw_art_path).convert("RGBA")
        else:
            base_img = Image.open(DEFAULT_THUMB).convert("RGBA")

    except Exception as e:
        print(f"[gen_thumb Error - Using Default] {e}")
        try:
            base_img = Image.open(DEFAULT_THUMB).convert("RGBA")
            title = "Sitara Music"
            duration = "Unknown"
            channel = "Sitara Music"
        except Exception:
            traceback.print_exc()
            return None

    try:
        total = _parse_seconds(duration)
        rng = _rng_for(f"{videoid}:{time.time():.0f}")
        progress = rng.uniform(0.08, 0.9) if total else 0.0

        out = _render(videoid, title, channel, total, progress, base_img, rng)

        if raw_art_path and Path(raw_art_path).exists():
            try:
                raw_art_path.unlink(missing_ok=True)
            except Exception:
                pass

        return out

    except Exception as e:
        print(f"[gen_thumb Processing Error] {e}")
        traceback.print_exc()
        return None
