"""Build every share card from the two photos and the live numbers.

Replaces make_og.py, which only made the link preview. Three outputs now:

  og.jpg            1200x630   link preview, used by the site, LinkedIn, iMessage
  share-square.jpg  1080x1080  LinkedIn or Instagram feed post
  share-post.jpg    1080x1350  Instagram feed post, 4:5, with an empty band at
                               the foot for a link sticker instead of a button
  share-story.jpg   1080x1920  Instagram story

All three read the same sources the page reads, so they cannot drift from it:

  miles, goal, date range  <- the RIDE block in index.html
  raised, donors, goal     <- data.json

The layout is a fade between the two photos rather than a hard split, so the
ride and what it was for sit in one frame instead of two panels.

Usage:
  python3 tools/make_cards.py           build all three
  python3 tools/make_cards.py --check   exit 1 if og.jpg's ?v= tag is stale
"""

import json
import os
import re
import sys

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GREEN = (0, 229, 124)
BLUE = (61, 90, 254)
WHITE = (245, 246, 248)
GREY = (138, 147, 171)
DARK = (7, 9, 14)

FONTS = "/System/Library/Fonts/Supplemental/"
F_BOLD = FONTS + "Arial Bold.ttf"
AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
AV_HEAVY, AV_BOLD, AV_DEMI = 8, 0, 2
SFNS = "/System/Library/Fonts/SFNS.ttf"         # SF Pro, the system face
SFNS_IT = "/System/Library/Fonts/SFNSItalic.ttf"
F_BLACK = FONTS + "Arial Black.ttf"
F_ITAL = FONTS + "Arial Bold Italic.ttf"

RIDE_IMG = ["hero-2600.avif", "hero-1120.jpg", "hero.jpg"]
MEDAL_IMG = ["gal-medal-1100.avif", "gal-medal-720.avif", "gal-medal.jpg"]


def font(path, size, index=None):
    try:
        if index is not None:
            return ImageFont.truetype(path, size, index=index)
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


def av(size, weight=None):
    """Avenir Next. Kept for the layouts that still use it."""
    return font(AVENIR, size, AV_HEAVY if weight is None else weight)


def graded_blur(im, soft=0.50, hard=0.74, mx=17):
    """Sharp at the top, easing into full blur at the bottom, rather than one
    flat blur over the whole thing. Three levels crossfaded down the frame: a
    straight two way blend reads as a ghost through the middle."""
    h = im.height
    out = im.copy()
    for lo, hi, radius in ((soft, hard + 0.10, mx * 0.42), (hard, 0.99, mx)):
        layer = im.filter(ImageFilter.GaussianBlur(radius))
        mask = Image.new("L", im.size, 0)
        md = ImageDraw.Draw(mask)
        for y in range(h):
            t = (y / h - lo) / max(1e-6, hi - lo)
            md.line([(0, y), (im.width, y)], fill=int(255 * min(1.0, max(0.0, t)) ** 1.1))
        out = Image.composite(layer, out, mask)
    return out


def gradtext(base, x, y, text, fnt, c0, c1):
    """Horizontal gradient inside the glyphs, the way h1 b is filled on the
    site: #6d82ff to #a9b6ff, left to right."""
    d = ImageDraw.Draw(base)
    w = int(d.textlength(text, font=fnt)) + 4
    h = int(fnt.size * 1.45)
    lay = Image.new("L", (w, h), 0)
    ImageDraw.Draw(lay).text((0, 0), text, font=fnt, fill=255)
    grad = Image.new("RGB", (w, h))
    gd = ImageDraw.Draw(grad)
    for i in range(w):
        t = i / max(1, w - 1)
        gd.line([(i, 0), (i, h)], fill=tuple(round(c0[k] + (c1[k] - c0[k]) * t) for k in range(3)))
    base.paste(grad, (int(x), int(y)), lay)
    return w - 4


def sfi(size, weight="Black Italic"):
    """The italic cut. index.html sets .miles italic at weight 900, so the big
    number has to be italic here too or it is simply a different typeface from
    the one on the page."""
    try:
        f = ImageFont.truetype(SFNS_IT, size)
        f.set_variation_by_name(weight)
        return f
    except Exception:
        return sf(size, "Black")


def milesnum(base, cx, y, text, size, track=-0.053, align="center"):
    """The number as the site draws it: italic 900, tight negative tracking,
    and a white to periwinkle gradient down the glyphs rather than flat white."""
    fnt = sfi(size)
    d = ImageDraw.Draw(base)
    sp = size * track
    w = sum(d.textlength(c, font=fnt) for c in text) + sp * (len(text) - 1)
    h = int(size * 1.25)
    lay = Image.new("L", (int(w) + size, h), 0)
    ld = ImageDraw.Draw(lay)
    x = 0
    for c in text:
        ld.text((x, 0), c, font=fnt, fill=255)
        x += d.textlength(c, font=fnt) + sp
    grad = Image.new("RGB", (lay.width, h))
    gd = ImageDraw.Draw(grad)
    for i in range(h):
        t = min(1.0, max(0.0, (i / h - 0.25) / 0.65))
        gd.line([(0, i), (lay.width, i)],
                fill=(round(255 + (143 - 255) * t),
                      round(255 + (161 - 255) * t),
                      round(255 + (255 - 255) * t)))
    x0 = cx if align == "left" else cx - w / 2
    base.paste(grad, (int(x0), int(y)), lay)
    return base, w


def sf(size, weight="Bold"):
    """SF Pro. It is a variable font, so the weight is set per instance rather
    than picked from a family. Avenir read soft and geometric next to the story
    this is meant to match; SF is the face that story was actually set in."""
    try:
        f = ImageFont.truetype(SFNS, size)
        f.set_variation_by_name(weight)
        return f
    except Exception:
        return font(AVENIR, size, AV_HEAVY)


def pick(names):
    for n in names:
        p = os.path.join(ROOT, n)
        if os.path.exists(p):
            return Image.open(p).convert("RGB")
    sys.exit("none of these exist: %s" % ", ".join(names))


def cover(im, bw, bh, px=0.5, py=0.5):
    """CSS object-fit: cover, with object-position."""
    s = max(bw / im.width, bh / im.height)
    r = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x, y = round((r.width - bw) * px), round((r.height - bh) * py)
    return r.crop((x, y, x + bw, y + bh))


def tracked(draw, xy, text, fnt, fill, sp=0):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + sp
    return x


def tracked_w(draw, text, fnt, sp=0):
    return sum(draw.textlength(c, font=fnt) for c in text) + sp * max(0, len(text) - 1)


def feather(base, top, box, axis, softness):
    """Composite `top` into `base` at `box`, dissolving across `softness` px."""
    x0, y0 = box
    w, h = top.size
    mask = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(mask)
    for i in range(int(softness)):
        v = int(255 * (i / softness))
        if axis == "x":
            d.line([(i, 0), (i, h)], fill=v)
        else:
            d.line([(0, i), (w, i)], fill=v)
    base.paste(top, (x0, y0), mask)
    return base


def scrim(im, box, strength, axis="x", invert=False):
    """Lay a directional darkening ramp over a region so text stays readable."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return im
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    n = w if axis == "x" else h
    for i in range(n):
        t = i / max(1, n - 1)
        if invert:
            t = 1 - t
        v = int(strength * 255 * (1 - t) ** 0.85)
        if axis == "x":
            d.line([(i, 0), (i, h)], fill=v)
        else:
            d.line([(0, i), (w, i)], fill=v)
    im.paste(Image.new("RGB", (w, h), DARK), (x0, y0), mask)
    return im


def glow_number(im, xy, text, fnt, colour=(200, 255, 224)):
    g = Image.new("RGB", im.size, (0, 0, 0))
    ImageDraw.Draw(g).text(xy, text, font=fnt, fill=(0, 118, 64))
    im = ImageChops.screen(im, g.filter(ImageFilter.GaussianBlur(im.width * 0.025)))
    ImageDraw.Draw(im).text(xy, text, font=fnt, fill=colour)
    return im


def bar(im, x0, x1, y, h, pct):
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([x0, y, x1, y + h], radius=h // 2, fill=(26, 32, 46))
    end = x0 + (x1 - x0) * pct
    if end <= x0:
        return im
    strip = Image.new("RGB", (max(1, int(end - x0)), h))
    sd = ImageDraw.Draw(strip)
    for x in range(strip.width):
        t = x / max(1, strip.width - 1)
        sd.line([(x, 0), (x, h)], fill=tuple(
            round(BLUE[i] + (GREEN[i] - BLUE[i]) * t) for i in range(3)))
    m = Image.new("L", strip.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, strip.width - 1, h - 1], radius=h // 2, fill=255)
    im.paste(strip, (x0, y), m)
    return im


def read_ride():
    src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    block = re.search(r"var RIDE = \{(.*?)\};", src, re.S)
    if not block:
        sys.exit("could not find the RIDE block in index.html")
    body = block.group(1)

    def num(k):
        m = re.search(k + r":\s*([\d.]+)", body)
        if not m:
            sys.exit("RIDE is missing %s" % k)
        return float(m.group(1))

    t = re.search(r"through:\s*'([^']*)'", body)
    rng = (t.group(1) if t else "").replace("&ndash;", " to ").replace("&mdash;", " to ")
    return num("done"), num("goal"), rng


def read_collective():
    """The whole challenge's total, which is not this rider's total."""
    src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    m = re.search(r"allRiders:\s*(\d+)", src)
    return int(m.group(1)) if m else 0


def read_money():
    try:
        d = json.load(open(os.path.join(ROOT, "data.json")))
        return int(d.get("raised") or 0), int(d.get("donors") or 0), int(d.get("goal") or 0)
    except (OSError, ValueError):
        return 0, 0, 0


# ---------------------------------------------------------------- layouts

def build_og(ride, medal, done, goal, rng, raised, money_goal):
    W, H, L = 1200, 630, 70
    seam = 690                      # the medal photo starts here and fades in
    base = cover(ride, W, H, 0.30, 0.45)
    base = base.point(lambda v: int(v * 0.46))
    m = cover(medal, W - seam + 130, H, 0.5, 0.5)
    base = feather(base, m, (seam - 130, 0), "x", 190)
    base = scrim(base, (0, 0, seam + 40, H), 0.97)

    d = ImageDraw.Draw(base)
    tracked(d, (L, 60), "CHALLENGE COMPLETE" if done >= goal else "THE 300 MILE CHALLENGE",
            sf(21, "Bold"), GREEN, 3.0)
    tracked(d, (L, 97), "BENEFITING THE AMERICAN CANCER SOCIETY", sf(17, "Medium"), GREY, 2.5)
    fh = sf(54, "Bold")
    d.text((L, 143), "Riding for a world", font=fh, fill=WHITE)
    d.text((L, 199), "with ", font=fh, fill=WHITE)
    d.text((L + d.textlength("with ", font=fh), 199), "less cancer.", font=fh, fill=BLUE)

    num = str(int(round(done)))
    base, nw = milesnum(base, L, 268, num, 148, align="left")
    d = ImageDraw.Draw(base)
    tracked(d, (L + nw + 26, 372), "OF %d MILES" % goal,
            sf(23, "Bold"), (150, 160, 180), 3.0)

    base = bar(base, L, seam - 40, 452, 12, min(1.0, done / goal))
    d = ImageDraw.Draw(base)
    fs = sf(20, "Medium")
    d.text((L, 484), "%d%% complete" % round(100 * done / goal), font=fs, fill=GREEN)
    if rng:
        d.text((L + d.textlength("100% complete", font=fs) + 34, 484), rng,
               font=fs, fill=(120, 130, 150))

    fc = sf(22, "Bold")
    lab = "DONATE ON GOFUNDME"
    cw = tracked_w(d, lab, fc, 2.0)
    d.rounded_rectangle([L, 540, L + cw + 56, 590], radius=25, fill=GREEN)
    tracked(d, (L + 28, 554), lab, fc, (6, 18, 12), 2.0)
    return base


def panel(base, y0, y1, W, fade=170):
    """Solid ground for type, with the photo above it dissolving into it."""
    d = ImageDraw.Draw(base)
    d.rectangle([0, y0, W, y1], fill=DARK)
    grad = Image.new("L", (W, fade), 0)
    gd = ImageDraw.Draw(grad)
    for i in range(fade):
        gd.line([(0, i), (W, i)], fill=int(255 * (i / fade) ** 0.85))
    base.paste(Image.new("RGB", (W, fade), DARK), (0, y0 - fade), grad)
    return base


def inset(base, im, box, radius=18):
    """A photo at its own aspect ratio, rounded, with a hairline edge."""
    x, y, w, h = box
    tile = cover(im, w, h, 0.32, 0.38)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    base.paste(tile, (x, y), mask)
    ring = Image.new("L", (w, h), 0)
    ImageDraw.Draw(ring).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius,
                                           outline=255, width=2)
    base.paste(Image.new("RGB", (w, h), (255, 255, 255)), (x, y),
               ring.point(lambda v: int(v * 0.22)))
    return base


def typeblock(base, x, y, W, done, goal, raised, donors, allriders, scale=1.0,
              cta=True, headline=True, right=None):
    """Everything below the photo. Nothing here sits on an image."""
    S = lambda v: max(1, round(v * scale))
    d = ImageDraw.Draw(base)
    tracked(d, (x, y), "CHALLENGE COMPLETE", sf(S(23), "Bold"), GREEN, S(3.4))
    tracked(d, (x, y + S(40)), "BENEFITING THE AMERICAN CANCER SOCIETY",
            sf(S(18), "Medium"), (150, 159, 178), S(2.6))

    num = str(int(round(done)))
    ny = y + S(80)
    base, nw = milesnum(base, x, ny, num, S(152), align="left")
    d = ImageDraw.Draw(base)
    tracked(d, (x + nw + S(26), ny + S(104)),
            "OF %d MILES" % goal, sf(S(26), "Bold"), (150, 160, 180), S(3.2))
    yy = ny + S(178)

    if headline:
        fh = sf(S(48), "Bold")
        d.text((x, yy), "Riding for a world", font=fh, fill=WHITE)
        d.text((x, yy + S(54)), "with ", font=fh, fill=WHITE)
        d.text((x + d.textlength("with ", font=fh), yy + S(54)), "less cancer.",
               font=fh, fill=BLUE)
        yy += S(136)

    base = bar(base, x, (right if right is not None else W - x), yy, S(13),
               min(1.0, done / goal))
    yy += S(36)
    d = ImageDraw.Draw(base)
    d.text((x, yy), "$%s raised  \u00b7  %d donors" % (format(raised, ","), donors),
           font=sf(S(23), "Medium"), fill=GREEN)
    if allriders:
        d.text((x, yy + S(34)),
               "$%s across every rider in the challenge" % format(allriders, ","),
               font=sf(S(18), "Medium"), fill=(112, 122, 142))
    yy += S(78)

    if cta:
        fc = sf(S(25), "Bold")
        lab = "DONATE ON GOFUNDME"
        cw = tracked_w(d, lab, fc, S(2.3))
        d.rounded_rectangle([x, yy, x + cw + S(62), yy + S(62)], radius=S(31), fill=GREEN)
        tracked(d, (x + S(31), yy + S(18)), lab, fc, (6, 18, 12), S(2.3))
    return base


def build_square(ride, medal, done, goal, rng, raised, money_goal, donors, allriders=0):
    W, H, L = 1080, 1080, 72
    PH = 540
    base = Image.new("RGB", (W, H), DARK)
    base.paste(cover(medal, W, PH, 0.5, 0.28), (0, 0))
    base = panel(base, PH, H, W, fade=150)
    base = typeblock(base, L, PH + 40, W, done, goal, raised, donors, allriders,
                     scale=0.86, cta=False, right=W - L - 334)
    base = inset(base, ride, (W - L - 300, H - 250, 300, 225))
    return base


def build_post(ride, medal, done, goal, raised, donors, allriders):
    """Odin big, the bike at the foot at its own shape, and an empty band under
    it. A feed post cannot carry a link, so that space is for a sticker."""
    W, H, L = 1080, 1350, 76
    PH, BLANK = 660, 1160
    IW, IH = 320, 240
    IX = W - L - IW
    base = Image.new("RGB", (W, H), DARK)
    # 0.30 keeps the medal in his hand inside the frame; 0.24 cropped it off.
    base.paste(cover(medal, W, PH, 0.5, 0.30), (0, 0))
    base = panel(base, PH, BLANK, W, fade=170)
    # Starts high enough that the last line clears the blank band; it was being
    # sliced in half by it.
    base = typeblock(base, L, PH + 44, W, done, goal, raised, donors, allriders,
                     scale=0.86, cta=False, right=IX - 34)
    base = inset(base, ride, (IX, BLANK - 300, IW, IH))
    d = ImageDraw.Draw(base)
    d.rectangle([0, BLANK, W, H], fill=DARK)
    return base


def ctext(d, cx, y, text, fnt, fill, sp=0):
    """Centred, with optional letter spacing."""
    w = tracked_w(d, text, fnt, sp)
    tracked(d, (cx - w / 2, y), text, fnt, fill, sp)
    return w


def skewbar(base, cx, y, w, h, pct, lean=14):
    """The website's progress track: a leaning parallelogram, blue on dark."""
    pad = lean
    strip = Image.new("RGBA", (w + pad * 2, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(strip)
    sd.polygon([(pad, 0), (w + pad, 0), (w + pad - lean, h), (pad - lean, h)],
               fill=(30, 36, 52, 255))
    fw = max(0, int(w * pct))
    if fw:
        sd.polygon([(pad, 0), (pad + fw, 0), (pad + fw - lean, h), (pad - lean, h)],
                   fill=(109, 130, 255, 255))
    base.paste(strip, (int(cx - w / 2 - pad), y), strip)
    return base


def pill(base, cx, y, w, h, label, fnt, bg, fg, arrow=True):
    """A button. The arrow is drawn, not typed: Avenir has no glyph for it and
    it was rendering as a tofu box."""
    d = ImageDraw.Draw(base)
    d.rounded_rectangle([cx - w / 2, y, cx + w / 2, y + h], radius=h // 2, fill=bg)
    tw = d.textlength(label, font=fnt)
    ax = 26 if arrow else 0
    tx = cx - (tw + ax) / 2
    d.text((tx, y + (h - fnt.size * 1.32) / 2), label, font=fnt, fill=fg)
    if arrow:
        ax0 = tx + tw + 16
        ay = y + h / 2
        d.line([(ax0, ay), (ax0 + 17, ay)], fill=fg, width=3)
        d.line([(ax0 + 10, ay - 7), (ax0 + 17, ay)], fill=fg, width=3)
        d.line([(ax0 + 10, ay + 7), (ax0 + 17, ay)], fill=fg, width=3)
    return base


def build_story(ride, medal, done, goal, rng, raised, money_goal, donors, allriders=0):
    W, H = 1080, 1920
    CX = W // 2
    TOP_H, CARD_Y = 400, 1240
    base = Image.new("RGB", (W, H), (7, 9, 14))

    # Blurred, but still legibly a person on a bike. The old version blurred it
    # into grey mush and read like a mistake.
    top = graded_blur(cover(ride, W, TOP_H, 0.32, 0.26))
    top = ImageEnhance.Brightness(top).enhance(0.93)
    base.paste(top, (0, 0))
    cap = Image.new("L", (W, 260), 0)
    cd0 = ImageDraw.Draw(cap)
    for i in range(260):
        cd0.line([(0, i), (W, i)], fill=int(200 * (1 - i / 260) ** 0.9))
    base.paste(Image.new("RGB", (W, 260), (7, 9, 14)), (0, 0), cap)
    fade = Image.new("L", (W, 150), 0)
    fd = ImageDraw.Draw(fade)
    for i in range(150):
        fd.line([(0, i), (W, i)], fill=int(255 * (i / 150) ** 0.75))
    base.paste(Image.new("RGB", (W, 150), (7, 9, 14)), (0, TOP_H - 150), fade)

    # The site's h1: weight 200, with the bold half filled by a blue gradient.
    d = ImageDraw.Draw(base)
    fl = sf(56, "Thin")
    fb = sf(56, "Heavy")
    l1 = "Riding for a world"
    d.text((CX - d.textlength(l1, font=fl) / 2, 78), l1, font=fl, fill=(245, 246, 248))
    w_with = d.textlength("with ", font=fl)
    w_bold = d.textlength("less cancer.", font=fb)
    x2 = CX - (w_with + w_bold) / 2
    d.text((x2, 146), "with ", font=fl, fill=(245, 246, 248))
    gradtext(base, x2 + w_with, 146, "less cancer.", fb, (109, 130, 255), (169, 182, 255))

    pct = done / goal
    num = str(int(round(done)))
    d = ImageDraw.Draw(base)
    base, _ = milesnum(base, CX, 430, num, 200)
    d = ImageDraw.Draw(base)
    # .goal on the site: 700, letter-spacing 4px at 17px, #8a93ab
    ctext(d, CX, 654, "OF %d MILES  \u00b7  %d%%" % (goal, round(pct * 100)),
          sf(38, "Bold"), (138, 147, 171), 8.5)

    # A plain rounded track, sized to the type above it, instead of a skewed
    # slash floating on its own.
    BW, BH, BY = 620, 8, 726
    d.rounded_rectangle([CX - BW / 2, BY, CX + BW / 2, BY + BH], radius=BH // 2,
                        fill=(32, 38, 54))
    fwid = int(BW * min(1.0, pct))
    if fwid:
        d.rounded_rectangle([CX - BW / 2, BY, CX - BW / 2 + fwid, BY + BH],
                            radius=BH // 2, fill=(255, 255, 255))

    permile = ("$%.2f a mile" % (raised / done)) if done else ""
    ctext(d, CX, 784, "$%s raised  \u00b7  %d donors  \u00b7  %s"
          % (format(raised, ","), donors, permile), sf(35, "Medium"), (255, 255, 255), 0.2)
    ctext(d, CX, 834, "Every ride verified on Strava", sf(26, "Regular"), (124, 134, 154), 0.4)
    if allriders:
        ctext(d, CX, 876, "$%s raised across the whole challenge" % format(allriders, ","),
              sf(25, "Regular"), (96, 105, 124), 0.4)

    base = pill(base, CX, 946, 548, 84, "Donate on GoFundMe", sf(34, "Semibold"),
                (0, 229, 124), (6, 20, 13))

    # 978 to 1064 stays clear for the link sticker.

    ctext(d, CX, 1102, "Cancer doesn't cut corners.", sf(35, "Semibold"), (255, 77, 109))
    ctext(d, CX, 1146, "Neither do we.", sf(35, "Semibold"), (255, 255, 255))
    ctext(d, CX, 1196, "vnaidu16.github.io/vn-ride-for-acs", sf(24, "Regular"), (110, 120, 140))

    # Two cards at the foot. Half the width is almost exactly the finisher
    # photo's own aspect ratio, so it is barely cropped at all.
    M, GAP, rad = 58, 22, 28
    CWd = (W - M * 2 - GAP) // 2
    CH = H - CARD_Y - 58
    mask = Image.new("L", (CWd, CH), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, CWd - 1, CH - 1], radius=rad, fill=255)

    base.paste(cover(medal, CWd, CH, 0.5, 0.30), (M, CARD_Y), mask)

    bx = M + CWd + GAP
    card = Image.new("RGB", (CWd, CH), (15, 18, 27))
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle([0, 0, CWd - 1, CH - 1], radius=rad, outline=(40, 47, 66), width=2)
    cd.text((30, 34), "Thank you", font=sf(31, "Semibold"), fill=(255, 255, 255))
    cd.text((30, 78), "%d people funded this" % donors, font=sf(22, "Regular"),
            fill=(120, 130, 150))
    # Faint rules so the space reads as a list waiting to be filled rather than
    # an empty box. V tags the donors over these.
    for i in range(6):
        yy = 146 + i * 62
        cd.line([(30, yy), (CWd - 30, yy)], fill=(30, 36, 52), width=2)
    base.paste(card, (bx, CARD_Y), mask)
    return base


def main():
    done, goal, rng = read_ride()
    raised, donors, money_goal = read_money()
    version = str(int(round(done)))

    if "--check" in sys.argv:
        src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
        tags = set(re.findall(r"og\.jpg\?v=([\d.]+)", src))
        if not os.path.exists(os.path.join(ROOT, "og.jpg")):
            sys.exit("og.jpg does not exist; run tools/make_cards.py")
        if tags != {version}:
            sys.exit("og.jpg cache tag is %s but the ride is at %s; rebuild and bump it"
                     % (sorted(tags) or ["none"], version))
        print("og.jpg is current at v=%s" % version)
        return

    allriders = read_collective()
    ride, medal = pick(RIDE_IMG), pick(MEDAL_IMG)
    jobs = [
        ("share-post.jpg",
         build_post(ride, medal, done, goal, raised, donors, allriders), 90),
        ("og.jpg", build_og(ride, medal, done, goal, rng, raised, money_goal), 88),
        ("share-square.jpg",
         build_square(ride, medal, done, goal, rng, raised, money_goal, donors, allriders), 90),
        ("share-story.jpg",
         build_story(ride, medal, done, goal, rng, raised, money_goal, donors, allriders), 90),
    ]
    for name, img, q in jobs:
        p = os.path.join(ROOT, name)
        img.save(p, "JPEG", quality=q, optimize=True, progressive=True)
        print("  %-18s %dx%d  %.0fKB" % (name, img.width, img.height,
                                         os.path.getsize(p) / 1024))
    print("\n%.0f/%.0f miles  %d%%  $%d from %d donors"
          % (done, goal, round(100 * done / goal), raised, donors))
    print("og:image and twitter:image should read og.jpg?v=%s" % version)


if __name__ == "__main__":
    main()
