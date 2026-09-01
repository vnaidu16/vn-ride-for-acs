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


def build_square(ride, medal, done, goal, rng, raised, money_goal, donors):
    W, H, L = 1080, 1080, 72
    panel = 700                      # imagery above, text below
    base = Image.new("RGB", (W, H), DARK)
    half = W // 2 + 60
    base.paste(cover(ride, half, panel, 0.32, 0.45), (0, 0))
    base = feather(base, cover(medal, W - half + 150, panel, 0.5, 0.5),
                   (half - 150, 0), "x", 200)
    base = scrim(base, (0, panel - 190, W, panel), 1.0, axis="y", invert=True)

    d = ImageDraw.Draw(base)
    tracked(d, (L, 44), "CHALLENGE COMPLETE" if done >= goal else "THE 300 MILE CHALLENGE",
            font(F_BLACK, 22), GREEN, 3.2)

    fn = font(F_ITAL, 178)
    num = str(int(round(done)))
    base = glow_number(base, (L, panel - 168), num, fn)
    d = ImageDraw.Draw(base)
    tracked(d, (L + d.textlength(num, font=fn) + 26, panel - 60), "OF %d MILES" % goal,
            font(F_BLACK, 26), (170, 180, 200), 3.2)

    fh = font(F_BLACK, 52)
    d.text((L, panel + 44), "Riding for a world", font=fh, fill=WHITE)
    d.text((L, panel + 102), "with ", font=fh, fill=WHITE)
    d.text((L + d.textlength("with ", font=fh), panel + 102), "less cancer.", font=fh, fill=BLUE)

    base = bar(base, L, W - L, panel + 190, 13, min(1.0, done / goal))
    d = ImageDraw.Draw(base)
    fs = font(F_BOLD, 23)
    stats = "$%s raised  ·  %d donors" % (format(raised, ","), donors)
    d.text((L, panel + 224), stats, font=fs, fill=GREEN)
    if rng:
        d.text((W - L - d.textlength(rng, font=fs), panel + 224), rng, font=fs, fill=(120, 130, 150))

    fc = font(F_BLACK, 24)
    lab = "DONATE ON GOFUNDME"
    cw = tracked_w(d, lab, fc, 2.2)
    d.rounded_rectangle([L, panel + 282, L + cw + 60, panel + 340], radius=29, fill=GREEN)
    tracked(d, (L + 30, panel + 298), lab, fc, (6, 18, 12), 2.2)
    return base


def build_story(ride, medal, done, goal, rng, raised, money_goal, donors, allriders=0):
    W, H, L = 1080, 1920, 84
    base = Image.new("RGB", (W, H), DARK)
    top = 760
    base.paste(cover(ride, W, top, 0.32, 0.45), (0, 0))
    # The medal photo is 3:4, so it gets the taller half and keeps its shape.
    base = feather(base, cover(medal, W, 1030, 0.5, 0.42), (0, top - 90), "y", 210)
    base = scrim(base, (0, H - 700, W, H), 1.0, axis="y", invert=True)
    base = scrim(base, (0, 0, W, 300), 0.9, axis="y")

    d = ImageDraw.Draw(base)
    tracked(d, (L, 96), "CHALLENGE COMPLETE" if done >= goal else "THE 300 MILE CHALLENGE",
            font(F_BLACK, 26), GREEN, 3.6)
    tracked(d, (L, 140), "BENEFITING THE AMERICAN CANCER SOCIETY",
            font(F_BOLD, 20), (190, 198, 214), 2.8)

    fn = font(F_ITAL, 250)
    num = str(int(round(done)))
    base = glow_number(base, (L, H - 690), num, fn)
    d = ImageDraw.Draw(base)
    tracked(d, (L + d.textlength(num, font=fn) + 30, H - 560), "OF %d MILES" % goal,
            font(F_BLACK, 32), (175, 185, 205), 3.6)

    fh = font(F_BLACK, 68)
    d.text((L, H - 452), "Riding for a world", font=fh, fill=WHITE)
    d.text((L, H - 376), "with ", font=fh, fill=WHITE)
    d.text((L + d.textlength("with ", font=fh), H - 376), "less cancer.", font=fh, fill=BLUE)

    base = bar(base, L, W - L, H - 268, 16, min(1.0, done / goal))
    d = ImageDraw.Draw(base)
    fs = font(F_BOLD, 28)
    d.text((L, H - 236), "$%s raised  ·  %d donors" % (format(raised, ","), donors),
           font=fs, fill=GREEN)
    if allriders:
        d.text((L, H - 198),
               "$%s across every rider in the challenge" % format(allriders, ","),
               font=font(F_BOLD, 19), fill=(122, 132, 152))

    fc = font(F_BLACK, 30)
    lab = "DONATE ON GOFUNDME"
    cw = tracked_w(d, lab, fc, 2.6)
    d.rounded_rectangle([L, H - 168, L + cw + 72, H - 92], radius=38, fill=GREEN)
    tracked(d, (L + 36, H - 147), lab, fc, (6, 18, 12), 2.6)
    return base


def build_post(ride, medal, done, goal, raised, donors, allriders):
    """Odin at the top, the bike at the foot, and a deliberately empty band
    below that. Instagram feed posts cannot carry a link, so the space is left
    for a sticker rather than filled with a button that would not work."""
    W, H, L = 1080, 1350, 76
    # Photo, then a band that carries all the type, then the bike, then nothing.
    # The number used to sit over the medal shot and landed square on his face.
    PHOTO, PIC, BLANK = 520, 884, 1124
    base = Image.new("RGB", (W, H), DARK)

    base.paste(cover(medal, W, PHOTO, 0.5, 0.28), (0, 0))
    base = scrim(base, (0, PHOTO - 200, W, PHOTO), 1.0, axis="y", invert=True)
    base = scrim(base, (0, 0, W, 200), 0.85, axis="y")

    d = ImageDraw.Draw(base)
    tracked(d, (L, 58), "CHALLENGE COMPLETE", font(F_BLACK, 23), GREEN, 3.4)
    tracked(d, (L, 100), "BENEFITING THE AMERICAN CANCER SOCIETY",
            font(F_BOLD, 18), (198, 206, 222), 2.6)

    fn = font(F_ITAL, 132)
    num = str(int(round(done)))
    base = glow_number(base, (L, PHOTO + 14), num, fn)
    d = ImageDraw.Draw(base)
    tracked(d, (L + d.textlength(num, font=fn) + 24, PHOTO + 96), "OF %d MILES" % goal,
            font(F_BLACK, 25), (170, 180, 200), 3.2)

    fh = font(F_BLACK, 43)
    d.text((L, PHOTO + 176), "Riding for a world", font=fh, fill=WHITE)
    d.text((L, PHOTO + 224), "with ", font=fh, fill=WHITE)
    d.text((L + d.textlength("with ", font=fh), PHOTO + 224), "less cancer.", font=fh, fill=BLUE)

    d.text((L, PHOTO + 292), "$%s raised here  \u00b7  %d donors"
           % (format(raised, ","), donors), font=font(F_BOLD, 22), fill=GREEN)
    if allriders:
        d.text((L, PHOTO + 326),
               "$%s raised across every rider in the challenge" % format(allriders, ","),
               font=font(F_BOLD, 17), fill=(116, 126, 146))

    base.paste(cover(ride, W, BLANK - PIC, 0.32, 0.34), (0, PIC))

    # Left empty on purpose: a feed post cannot carry a link, so this is room
    # for a sticker rather than a button that would not do anything.
    d = ImageDraw.Draw(base)
    d.rectangle([0, BLANK, W, H], fill=DARK)
    base = scrim(base, (0, BLANK - 80, W, BLANK), 1.0, axis="y", invert=True)
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
         build_square(ride, medal, done, goal, rng, raised, money_goal, donors), 90),
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
