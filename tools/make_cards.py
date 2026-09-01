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

RIDE_IMG = ["hero-3000.avif", "hero-2600.avif", "hero.jpg"]
MEDAL_IMG = ["gal-medal-2400.avif", "gal-medal-1600.avif", "gal-medal.jpg"]


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


MDOT_RED = (237, 28, 36)


def mdot(base, x, y, h, colour=MDOT_RED):
    """The IRONMAN mark, same geometry as the SVG in index.html: a disc over an
    M drawn as a stroked polyline on a 40x34 grid. Drawn oversampled and scaled
    down, because a 7.2 unit stroke at this size is a couple of pixels wide and
    aliases badly otherwise."""
    OS = 8
    u = h * OS / 34.0
    w = round(40 * u)
    lay = Image.new("L", (w, round(34 * u)), 0)
    ld = ImageDraw.Draw(lay)
    ld.ellipse([(20 - 6.1) * u, (6.6 - 6.1) * u, (20 + 6.1) * u, (6.6 + 6.1) * u], fill=255)
    pts = [(4 * u, 32.5 * u), (4 * u, 17.6 * u), (20 * u, 28.8 * u),
           (36 * u, 17.6 * u), (36 * u, 32.5 * u)]
    ld.line(pts, fill=255, width=round(7.2 * u), joint="curve")
    lay = lay.resize((round(w / OS), round(34 * u / OS)), Image.LANCZOS)
    base.paste(Image.new("RGB", lay.size, colour), (round(x), round(y)), lay)
    return lay.size[0]


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


def ctext(d, cx, y, text, fnt, fill, sp=0):
    """Centred, with optional letter spacing."""
    w = tracked_w(d, text, fnt, sp)
    tracked(d, (cx - w / 2, y), text, fnt, fill, sp)
    return w


def skewbar(base, cx, y, w, h, pct, lean=14):
    """A leaning progress track, the shape the site uses."""
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
    """A button, with the arrow drawn rather than typed."""
    d = ImageDraw.Draw(base)
    d.rounded_rectangle([cx - w / 2, y, cx + w / 2, y + h], radius=h // 2, fill=bg)
    tw = d.textlength(label, font=fnt)
    ax = h * 0.30 if arrow else 0
    tx = cx - (tw + ax) / 2
    d.text((tx, y + (h - fnt.size * 1.32) / 2), label, font=fnt, fill=fg)
    if arrow:
        a0, ay, r = tx + tw + h * 0.18, y + h / 2, h * 0.20
        wd = max(2, round(h * 0.035))
        d.line([(a0, ay), (a0 + r, ay)], fill=fg, width=wd)
        d.line([(a0 + r * 0.6, ay - r * 0.42), (a0 + r, ay)], fill=fg, width=wd)
        d.line([(a0 + r * 0.6, ay + r * 0.42), (a0 + r, ay)], fill=fg, width=wd)
    return base


def build_post(ride, medal, done, goal, raised, donors, allriders, k=2):
    """Odin big, the bike inset at the foot, an empty band for a sticker, and
    the IRONMAN mark small underneath. Rendered at k times feed size."""
    P = lambda v: round(v * k)
    W, H, L = P(1080), P(1350), P(76)
    PH, BLANK = P(660), P(1160)
    IW, IH = P(320), P(240)
    IX = W - L - IW
    base = Image.new("RGB", (W, H), DARK)
    mw2, mh2 = medal.size
    tight = medal.crop((round(mw2 * 0.06), round(mh2 * 0.10),
                        round(mw2 * 0.97), round(mh2 * 0.99)))
    base.paste(cover(tight, W, PH, 0.5, 0.26), (0, 0))
    base = panel(base, PH, BLANK, W, fade=P(170))
    base = typeblock(base, L, PH + P(44), W, done, goal, raised, donors, allriders,
                     scale=0.86 * k, cta=False, right=IX - P(34))
    base = inset(base, ride, (IX, BLANK - P(300), IW, IH), radius=P(18))
    d = ImageDraw.Draw(base)
    d.rectangle([0, BLANK, W, H], fill=DARK)

    lab, flab = "IRONMAN 70.3 NEXT", sf(P(23), "Semibold")
    mh = P(30)
    mw = round(40 * mh / 34.0)
    tw = tracked_w(d, lab, flab, P(2.6))
    gx = (W - (mw + P(16) + tw)) / 2
    mdot(base, gx, H - P(74), mh)
    d = ImageDraw.Draw(base)
    tracked(d, (gx + mw + P(16), H - P(70)), lab, flab, (128, 137, 156), P(2.6))
    return base


def build_story(ride, medal, done, goal, rng, raised, money_goal, donors, allriders=0,
                k=2):
    """Rendered at k times story size and left there. Instagram downsamples,
    and downsampling from 2160x3840 is far cleaner than uploading 1080 wide and
    letting it stretch. Every measurement below is in story points, scaled once.
    """
    P = lambda v: round(v * k)
    W, H = P(1080), P(1920)
    CX = W // 2
    TOP_H, CARD_Y = P(400), P(1218)
    base = Image.new("RGB", (W, H), (7, 9, 14))

    top = graded_blur(cover(ride, W, TOP_H, 0.32, 0.26), mx=P(17))
    top = ImageEnhance.Brightness(top).enhance(0.93)
    base.paste(top, (0, 0))
    cap = Image.new("L", (W, P(260)), 0)
    cd0 = ImageDraw.Draw(cap)
    for i in range(P(260)):
        cd0.line([(0, i), (W, i)], fill=int(200 * (1 - i / P(260)) ** 0.9))
    base.paste(Image.new("RGB", (W, P(260)), (7, 9, 14)), (0, 0), cap)
    fade = Image.new("L", (W, P(150)), 0)
    fd = ImageDraw.Draw(fade)
    for i in range(P(150)):
        fd.line([(0, i), (W, i)], fill=int(255 * (i / P(150)) ** 0.75))
    base.paste(Image.new("RGB", (W, P(150)), (7, 9, 14)), (0, TOP_H - P(150)), fade)

    d = ImageDraw.Draw(base)
    fl, fb = sf(P(56), "Thin"), sf(P(56), "Heavy")
    l1 = "Riding for a world"
    d.text((CX - d.textlength(l1, font=fl) / 2, P(78)), l1, font=fl, fill=(245, 246, 248))
    w_with = d.textlength("with ", font=fl)
    w_bold = d.textlength("less cancer.", font=fb)
    x2 = CX - (w_with + w_bold) / 2
    d.text((x2, P(146)), "with ", font=fl, fill=(245, 246, 248))
    gradtext(base, x2 + w_with, P(146), "less cancer.", fb, (109, 130, 255), (169, 182, 255))

    pct = done / goal
    num = str(int(round(done)))
    base, _ = milesnum(base, CX, P(400), num, P(120))
    d = ImageDraw.Draw(base)
    ctext(d, CX, P(534), "OF %d MILES  \u00b7  %d%%" % (goal, round(pct * 100)),
          sf(P(32), "Bold"), (138, 147, 171), P(7))

    permile = ("$%.2f a mile" % (raised / done)) if done else ""
    ctext(d, CX, P(584), "$%s raised  \u00b7  %d donors  \u00b7  %s"
          % (format(raised, ","), donors, permile), sf(P(33), "Medium"), (255, 255, 255), P(0.2))
    ctext(d, CX, P(624), "Every ride verified on Strava",
          sf(P(26), "Regular"), (124, 134, 154), P(0.4))
    if allriders:
        ctext(d, CX, P(658), "$%s raised across the whole challenge" % format(allriders, ","),
              sf(P(25), "Regular"), (96, 105, 124), P(0.4))

    base = pill(base, CX, P(696), P(512), P(70), "Donate on GoFundMe",
                sf(P(31), "Semibold"), (0, 229, 124), (6, 20, 13))

    # P(766) to P(840): kept clear for the link sticker.

    ctext(d, CX, P(850), "Cancer doesn't cut corners.", sf(P(32), "Semibold"), (255, 77, 109))
    ctext(d, CX, P(886), "Neither do we.", sf(P(32), "Semibold"), (255, 255, 255))
    ctext(d, CX, P(924), "vnaidu16.github.io/vn-ride-for-acs",
          sf(P(22), "Regular"), (110, 120, 140))

    CARD_Y = P(958)
    M, GAP, rad = P(28), P(16), P(32)
    CWd = (W - M * 2 - GAP) // 2
    CH = H - CARD_Y - P(36)
    mask = Image.new("L", (CWd, CH), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, CWd - 1, CH - 1], radius=rad, fill=255)

    # Tighter on the two of them: the full frame carried a lot of hallway.
    mw, mh = medal.size
    # Bottom edge stays: V confirmed it. The top comes down to 22%, which takes
    # out most of the hallway above his cap. Past about 25% the source turns
    # wide enough relative to this card that cover starts eating Odin's side.
    tight = medal.crop((0, round(mh * 0.22), mw, round(mh * 0.99)))
    base.paste(cover(tight, CWd, CH, 0.45, 0.5), (M, CARD_Y), mask)

    bx = M + CWd + GAP
    card = Image.new("RGB", (CWd, CH), (15, 18, 27))
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle([0, 0, CWd - 1, CH - 1], radius=rad, outline=(40, 47, 66), width=P(2))
    cd.text((P(34), P(44)), "Thank you", font=sf(P(44), "Semibold"), fill=(255, 255, 255))
    cd.text((P(34), P(106)), "to the %d people" % donors, font=sf(P(32), "Regular"),
            fill=(168, 178, 198))
    cd.text((P(34), P(148)), "that funded this", font=sf(P(32), "Regular"),
            fill=(168, 178, 198))
    for i in range(6):
        yy = P(240) + i * P(92)
        cd.line([(P(34), yy), (CWd - P(34), yy)], fill=(30, 36, 52), width=P(2))
    # A line at the foot on what the money actually does. Kept to research and
    # patient support, which is what ACS funds, rather than a broader claim the
    # rest of this page would not stand behind.
    fnote = sf(P(21), "Regular")
    cd.text((P(34), P(816)), "Your donation funds cancer", font=fnote, fill=(112, 122, 142))
    cd.text((P(34), P(846)), "research and patient support.", font=fnote, fill=(112, 122, 142))
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
         build_post(ride, medal, done, goal, raised, donors, allriders), 95),
        ("og.jpg", build_og(ride, medal, done, goal, rng, raised, money_goal), 88),
        ("share-square.jpg",
         build_square(ride, medal, done, goal, rng, raised, money_goal, donors, allriders), 90),
        ("share-story.jpg",
         build_story(ride, medal, done, goal, rng, raised, money_goal, donors, allriders), 95),
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
