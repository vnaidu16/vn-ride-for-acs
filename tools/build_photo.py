"""Build a responsive ladder for any photo on the site.

build_hero.py is hard-wired to the hero's widths and filenames. This is the
general version, for the celebration frames and whatever else gets added.

Two grades:
  full   the night-riding look from grade_hero.py, cool shadows and all
  light  contrast and a vignette only, for warm indoor shots the full grade
         fights by draining them blue

Usage:
  python3 tools/build_photo.py <src> <basename> [--rotate N] [--grade light]
                               [--widths 480,720,960,1200]
                               [--crop l,t,r,b]   fractions of the frame, 0-1

Writes <basename>-<w>.avif/.webp. Pass --jpeg for a full size jpeg as well;
the gallery does not need one, since its <img src> points at a webp and every
browser that lacks webp also lacks the rest of the page.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from grade_hero import apply_vignette, grade  # noqa: E402
from PIL import Image, ImageEnhance  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_WIDTHS = [480, 720, 960, 1200]


def light_grade(im, width):
    """Keep the warmth. Just shape it a little and roll the corners off."""
    im = im.convert("RGB")
    if width and im.width != width:
        h = round(im.height * width / im.width)
        im = im.resize((width, h), Image.LANCZOS)
    im = ImageEnhance.Color(im).enhance(0.96)
    im = ImageEnhance.Contrast(im).enhance(1.10)
    im = ImageEnhance.Brightness(im).enhance(0.97)
    return apply_vignette(im, 0.30)


def arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    positional = [a for i, a in enumerate(sys.argv[1:], 1)
                  if not a.startswith("--") and not (sys.argv[i - 1].startswith("--"))]
    if len(positional) < 2:
        sys.exit(__doc__)
    src, base = positional[0], positional[1]
    if not os.path.exists(src):
        sys.exit("no such file: %s" % src)

    rot = int(arg("--rotate", 0)) % 360
    style = arg("--grade", "full")
    widths = [int(w) for w in arg("--widths", ",".join(map(str, DEFAULT_WIDTHS))).split(",")]

    crop = arg("--crop")
    box = [float(v) for v in crop.split(",")] if crop else None

    def load():
        im = Image.open(src)
        if rot:
            im = im.convert("RGB").rotate(rot, expand=True)
            im.info.pop("exif", None)  # else grade() transposes it a second time
        if box:
            w, h = im.size
            im = im.crop((round(box[0] * w), round(box[1] * h),
                          round(box[2] * w), round(box[3] * h)))
        return im

    probe = load()
    print("source %dx%d  aspect %.3f  grade=%s" % (probe.width, probe.height,
                                                   probe.width / probe.height, style))
    if probe.width < max(widths):
        print("  note: source is %dpx, narrower than the %dpx tier requested"
              % (probe.width, max(widths)))

    for i, w in enumerate(widths):
        im = light_grade(load(), w) if style == "light" else grade(load(), w, grain=(w <= 1200))
        line = []
        for fmt, ext, kw in (("AVIF", "avif", dict(quality=52)),
                             ("WEBP", "webp", dict(quality=74, method=6))):
            p = os.path.join(ROOT, "%s-%d.%s" % (base, w, ext))
            im.save(p, fmt, **kw)
            line.append("%s %.0fKB" % (ext, os.path.getsize(p) / 1024))
        if i == len(widths) - 1 and "--jpeg" in sys.argv:
            p = os.path.join(ROOT, "%s.jpg" % base)
            im.save(p, "JPEG", quality=88, optimize=True, progressive=True)
            line.append("jpg %.0fKB" % (os.path.getsize(p) / 1024))
        print("  %-5d %dx%d  %s" % (w, im.width, im.height, "  ".join(line)))

    print()
    print("  " + ", ".join("%s-%d.avif %dw" % (base, w, w) for w in widths))


if __name__ == "__main__":
    main()
