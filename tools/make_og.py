"""Rebuild og.jpg, the 1200x630 card that unfurls when the link is shared.

This used to be drawn on a canvas in the browser and POSTed to a throwaway
local server, which meant it only ever got regenerated when someone remembered
to do the dance. It had gone stale at least once. Now it reads the same two
sources the page reads and can be run from the terminal in a second.

  miles, goal, date range  <- the RIDE block in index.html
  raised, donors           <- data.json

Usage:
  python3 tools/make_og.py            rebuild og.jpg and print the ?v= value
  python3 tools/make_og.py --check    exit 1 if og.jpg is out of date

After rebuilding, bump the ?v= on the og:image and twitter:image tags so the
scrapers refetch. --check is what tells you that is needed.
"""

import json
import os
import re
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1200, 630

GREEN = (0, 229, 124)
BLUE = (61, 90, 254)
WHITE = (245, 246, 248)
GREY = (138, 147, 171)

FONTS = "/System/Library/Fonts/Supplemental/"
F_BOLD = FONTS + "Arial Bold.ttf"
F_BLACK = FONTS + "Arial Black.ttf"
F_ITAL = FONTS + "Arial Bold Italic.ttf"


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


def tracked(draw, xy, text, fnt, fill, spacing=0):
    """Draw with letter spacing, which Pillow has no native support for."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + spacing
    return x


def tracked_width(draw, text, fnt, spacing=0):
    return sum(draw.textlength(c, font=fnt) for c in text) + spacing * max(0, len(text) - 1)


def read_ride():
    """Pull the RIDE constants out of index.html rather than duplicating them."""
    src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    block = re.search(r"var RIDE = \{(.*?)\};", src, re.S)
    if not block:
        sys.exit("could not find the RIDE block in index.html")
    body = block.group(1)

    def num(key):
        m = re.search(key + r":\s*([\d.]+)", body)
        if not m:
            sys.exit("RIDE is missing %s" % key)
        return float(m.group(1))

    through = re.search(r"through:\s*'([^']*)'", body)
    rng = through.group(1) if through else ""
    rng = rng.replace("&ndash;", " to ").replace("&mdash;", " to ")
    return num("done"), num("goal"), rng


def read_money():
    try:
        d = json.load(open(os.path.join(ROOT, "data.json")))
        return int(d.get("raised") or 0), int(d.get("goal") or 0)
    except (OSError, ValueError):
        return 0, 0


def build(done, goal, rng):
    pct = min(1.0, done / goal) if goal else 0.0
    complete = done >= goal

    # Background: the hero, darkened hard on the left so text stays legible.
    base = Image.new("RGB", (W, H), (8, 10, 15))
    for name in ("hero.jpg", "hero-1120.jpg", "hero-800.jpg"):
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            im = Image.open(p).convert("RGB")
            scale = max(W / im.width, H / im.height)
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            base.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
            break

    base = base.point(lambda v: int(v * 0.55))
    shade = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(shade)
    for x in range(W):
        # Near solid behind the copy, easing off only once past the headline.
        t = max(0.0, min(1.0, (x - 40) / (W * 1.02)))
        sd.line([(x, 0), (x, H)], fill=int(248 * (1 - t) ** 1.25))
    base = Image.composite(Image.new("RGB", (W, H), (7, 9, 14)), base, shade)

    d = ImageDraw.Draw(base)
    L = 70

    kicker = "CHALLENGE COMPLETE" if complete else "THE 300 MILE CHALLENGE"
    tracked(d, (L, 62), kicker, font(F_BLACK, 22), GREEN, 3.0)
    tracked(d, (L, 100), "BENEFITING THE AMERICAN CANCER SOCIETY",
            font(F_BOLD, 18), GREY, 2.6)

    f_head = font(F_BLACK, 58)
    d.text((L, 148), "Riding for a world", font=f_head, fill=WHITE)
    d.text((L, 208), "with ", font=f_head, fill=WHITE)
    d.text((L + d.textlength("with ", font=f_head), 208), "less cancer.",
           font=f_head, fill=BLUE)

    # The number, with the glow it has on the page.
    f_num = font(F_ITAL, 150)
    num = str(int(round(done)))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(glow).text((L, 290), num, font=f_num, fill=(0, 118, 64))
    base = ImageChops.screen(base, glow.filter(ImageFilter.GaussianBlur(30)))
    d = ImageDraw.Draw(base)
    d.text((L, 290), num, font=f_num, fill=(200, 255, 224))

    nw = d.textlength(num, font=f_num)
    f_of = font(F_BLACK, 24)
    tracked(d, (L + nw + 26, 392), "OF %d MILES" % goal, f_of, (150, 160, 180), 3.0)

    # Progress bar, blue to green across its filled length.
    by, bh = 462, 12
    d.rounded_rectangle([L, by, W - L, by + bh], radius=bh // 2, fill=(26, 32, 46))
    end = L + (W - 2 * L) * pct
    if end > L:
        bar = Image.new("RGB", (max(1, int(end - L)), bh))
        bd = ImageDraw.Draw(bar)
        for x in range(bar.width):
            t = x / max(1, bar.width - 1)
            bd.line([(x, 0), (x, bh)], fill=(
                round(BLUE[0] + (GREEN[0] - BLUE[0]) * t),
                round(BLUE[1] + (GREEN[1] - BLUE[1]) * t),
                round(BLUE[2] + (GREEN[2] - BLUE[2]) * t)))
        mask = Image.new("L", bar.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, bar.width - 1, bh - 1],
                                               radius=bh // 2, fill=255)
        base.paste(bar, (L, by), mask)

    f_small = font(F_BOLD, 21)
    d.text((L, by + 34), "%d%% complete" % round(pct * 100), font=f_small, fill=GREEN)
    if rng:
        d.text((W - L - d.textlength(rng, font=f_small), by + 34), rng,
               font=f_small, fill=(120, 130, 150))

    # The ask.
    f_cta = font(F_BLACK, 23)
    label = "DONATE ON GOFUNDME"
    cw = tracked_width(d, label, f_cta, 2.0)
    d.rounded_rectangle([L, 545, L + cw + 60, 596], radius=26, fill=GREEN)
    tracked(d, (L + 30, 559), label, f_cta, (6, 18, 12), 2.0)
    return base


def main():
    done, goal, rng = read_ride()
    out = os.path.join(ROOT, "og.jpg")
    version = str(int(round(done)))

    if "--check" in sys.argv:
        src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
        tags = set(re.findall(r"og\.jpg\?v=([\d.]+)", src))
        if not os.path.exists(out):
            sys.exit("og.jpg does not exist; run tools/make_og.py")
        if tags != {version}:
            sys.exit("og.jpg cache tag is %s but the ride is at %s; rebuild and bump it"
                     % (sorted(tags) or ["none"], version))
        print("og.jpg is current at v=%s" % version)
        return

    img = build(done, goal, rng)
    img.save(out, "JPEG", quality=88, optimize=True, progressive=True)
    raised, money_goal = read_money()
    print("wrote %s  %.0f/%.0f miles  %d%%  $%d raised"
          % (out, done, goal, round(100 * done / goal), raised))
    print("set the og:image and twitter:image tags to og.jpg?v=%s" % version)


if __name__ == "__main__":
    main()
