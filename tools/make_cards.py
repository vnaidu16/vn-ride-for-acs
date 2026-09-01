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

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GREEN = (0, 229, 124)
BLUE = (61, 90, 254)
WHITE = (245, 246, 248)
GREY = (138, 147, 171)
DARK = (7, 9, 14)

FONTS = "/System/Library/Fonts/Supplemental/"
F_BOLD = FONTS + "Arial Bold.ttf"
F_BLACK = FONTS + "Arial Black.ttf"
F_ITAL = FONTS + "Arial Bold Italic.ttf"

RIDE_IMG = ["hero-2600.avif", "hero-1120.jpg", "hero.jpg"]
MEDAL_IMG = ["gal-medal-1100.avif", "gal-medal-720.avif", "gal-medal.jpg"]


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


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
            font(F_BLACK, 21), GREEN, 3.0)
    tracked(d, (L, 97), "BENEFITING THE AMERICAN CANCER SOCIETY", font(F_BOLD, 17), GREY, 2.5)
    fh = font(F_BLACK, 54)
    d.text((L, 143), "Riding for a world", font=fh, fill=WHITE)
    d.text((L, 199), "with ", font=fh, fill=WHITE)
    d.text((L + d.textlength("with ", font=fh), 199), "less cancer.", font=fh, fill=BLUE)

    fn = font(F_ITAL, 140)
    num = str(int(round(done)))
    base = glow_number(base, (L, 278), num, fn)
    d = ImageDraw.Draw(base)
    tracked(d, (L + d.textlength(num, font=fn) + 24, 372), "OF %d MILES" % goal,
            font(F_BLACK, 23), (150, 160, 180), 3.0)

    base = bar(base, L, seam - 40, 452, 12, min(1.0, done / goal))
    d = ImageDraw.Draw(base)
    fs = font(F_BOLD, 20)
    d.text((L, 484), "%d%% complete" % round(100 * done / goal), font=fs, fill=GREEN)
    if rng:
        d.text((L + d.textlength("100% complete", font=fs) + 34, 484), rng,
               font=fs, fill=(120, 130, 150))

    fc = font(F_BLACK, 22)
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
    tracked(d, (x, y), "CHALLENGE COMPLETE", font(F_BLACK, S(23)), GREEN, S(3.4))
    tracked(d, (x, y + S(40)), "BENEFITING THE AMERICAN CANCER SOCIETY",
            font(F_BOLD, S(18)), (150, 159, 178), S(2.6))

    fn = font(F_ITAL, S(150))
    num = str(int(round(done)))
    ny = y + S(88)
    base = glow_number(base, (x, ny), num, fn)
    d = ImageDraw.Draw(base)
    tracked(d, (x + d.textlength(num, font=fn) + S(24), ny + S(96)),
            "OF %d MILES" % goal, font(F_BLACK, S(26)), (150, 160, 180), S(3.2))
    yy = ny + S(178)

    if headline:
        fh = font(F_BLACK, S(48))
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
           font=font(F_BOLD, S(23)), fill=GREEN)
    if allriders:
        d.text((x, yy + S(34)),
               "$%s across every rider in the challenge" % format(allriders, ","),
               font=font(F_BOLD, S(18)), fill=(112, 122, 142))
    yy += S(78)

    if cta:
        fc = font(F_BLACK, S(25))
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


def build_story(ride, medal, done, goal, rng, raised, money_goal, donors, allriders=0):
    """Rebuilt to match the story V actually liked: the photo full bleed, one
    big white number over it, and a compact stack of facts on the darkened
    lower third. No panels, no cropping the photo into a strip."""
    W, H = 1080, 1920
    CX = W // 2
    BIKE_H, MEDAL_END = 380, 1120
    base = Image.new("RGB", (W, H), (5, 7, 11))

    # Bike small across the top, Odin large beneath it as the one that carries
    # the post. The type sits on the lower part of Odin once it is dark enough,
    # and on flat ground below that.
    base.paste(cover(ride, W, BIKE_H, 0.32, 0.30), (0, 0))
    base.paste(cover(medal, W, MEDAL_END - BIKE_H, 0.5, 0.28), (0, BIKE_H))

    # Only the last stretch of the photo fades out, so the medal in his hand is
    # never sat on. The number goes underneath on flat ground instead.
    grad = Image.new("L", (W, MEDAL_END), 0)
    gd = ImageDraw.Draw(grad)
    for i in range(MEDAL_END):
        t = max(0.0, (i - 990) / 130.0)
        gd.line([(0, i), (W, i)], fill=int(min(1.0, t) ** 1.1 * 252))
    base.paste(Image.new("RGB", (W, MEDAL_END), (5, 7, 11)), (0, 0), grad)

    pct = done / goal
    num = str(int(round(done)))
    fn = font(F_BLACK, 178)
    d = ImageDraw.Draw(base)
    d.text((CX - d.textlength(num, font=fn) / 2, 1128), num, font=fn, fill=(255, 255, 255))

    ctext(d, CX, 1336, "OF %d MILES  \u00b7  %d%%" % (goal, round(pct * 100)),
          font(F_BLACK, 42), (232, 236, 244), 1.5)
    base = skewbar(base, CX, 1400, 760, 18, min(1.0, pct))
    d = ImageDraw.Draw(base)

    permile = ("$%.2f A MILE" % (raised / done)) if done else ""
    ctext(d, CX, 1450, "$%s RAISED  \u00b7  %d DONORS  \u00b7  %s"
          % (format(raised, ","), donors, permile), font(F_BLACK, 36), (255, 255, 255), 0.5)
    ctext(d, CX, 1500, "EVERY RIDE VERIFIED ON STRAVA", font(F_BOLD, 26), (128, 146, 255), 1.2)
    if allriders:
        ctext(d, CX, 1538, "$%s RAISED ACROSS THE WHOLE CHALLENGE" % format(allriders, ","),
              font(F_BOLD, 24), (132, 142, 162), 1.0)

    fc = font(F_BLACK, 38)
    lab = "DONATE ON GOFUNDME  \u2192"
    cw = tracked_w(d, lab, fc, 1.0)
    d.rounded_rectangle([CX - cw / 2 - 40, 1590, CX + cw / 2 + 40, 1674], radius=42, fill=GREEN)
    tracked(d, (CX - cw / 2, 1612), lab, fc, (5, 20, 12), 1.0)

    # 1686 to 1772 stays clear: that is where the link sticker goes. On the old
    # one the sticker landed on top of the button.

    ctext(d, CX, 1786, "Cancer doesn't cut corners.", font(F_BLACK, 37), (255, 77, 109))
    ctext(d, CX, 1832, "Neither do we.", font(F_BLACK, 37), (255, 255, 255))
    ctext(d, CX, 1874, "vnaidu16.github.io/vn-ride-for-acs", font(F_BOLD, 25), (120, 130, 150))
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
