"""Build the whole hero ladder from the untouched original.

The site shipped for a week with nothing wider than 1500px, so on any Retina
display the browser needed roughly 2940 device pixels and had to upscale what
it was given. The grading was never the problem; there simply were not enough
pixels. This rebuilds every size and format from the 4032px original.

Grain is part of the look at 1x. Above that it sits below the perceptual
threshold once the display halves it, while costing 20% in AVIF and 50% in
WebP, so the 2x tiers are built clean.

Nothing here writes EXIF. The original is a phone photo and carries GPS.

Some phone shots carry an orientation tag that does not match the pixels, so
--rotate applies a plain rotation instead of trusting EXIF.

Usage: python3 tools/build_hero.py <original.jpg> [--rotate 180]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from grade_hero import grade  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# width, keep grain, emit a jpeg too
TIERS = [
    (800, True, True),
    (1120, True, True),
    (1500, True, True),
    (2000, False, False),
    (2600, False, False),
    (3000, False, False),
]

BASE = 1500  # the width that keeps the bare "hero.*" name, for the src fallback


def name(width, ext):
    return "hero.%s" % ext if width == BASE else "hero-%d.%s" % (width, ext)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    if not os.path.exists(src):
        sys.exit("no such file: %s" % src)
    rot = 0
    if "--rotate" in sys.argv:
        rot = int(sys.argv[sys.argv.index("--rotate") + 1]) % 360

    def load():
        im = Image.open(src)
        if rot:
            im = im.convert("RGB").rotate(rot, expand=True)
            # rotate() carries .info across, so the orientation tag would still
            # be there and grade()'s exif_transpose would rotate a second time.
            # Dropping it is the whole point of passing --rotate.
            im.info.pop("exif", None)
        return im

    probe = load()
    if probe.width < max(w for w, _, _ in TIERS):
        sys.exit("source is only %dpx wide; the ladder needs %dpx"
                 % (probe.width, max(w for w, _, _ in TIERS)))
    print("source %dx%d" % probe.size)

    total = 0
    for width, grain, want_jpeg in TIERS:
        im = grade(load(), width, grain=grain)
        outs = [("AVIF", "avif", dict(quality=50)),
                ("WEBP", "webp", dict(quality=72, method=6))]
        if want_jpeg:
            outs.append(("JPEG", "jpg", dict(quality=88, optimize=True, progressive=True)))
        line = []
        for fmt, ext, kw in outs:
            p = os.path.join(ROOT, name(width, ext))
            im.save(p, fmt, **kw)
            kb = os.path.getsize(p) / 1024
            total += kb
            line.append("%s %.0fKB" % (ext, kb))
        print("  %-4d %sgrain  %s" % (width, " " if grain else "no ", "  ".join(line)))

    print("ladder total %.0fKB across %d files" % (total, sum(2 + t[2] for t in TIERS)))
    print()
    print("srcset (avif/webp):")
    print("  " + ", ".join("%s %dw" % (name(w, "avif"), w) for w, _, _ in TIERS))
    print("srcset (jpeg fallback):")
    print("  " + ", ".join("%s %dw" % (name(w, "jpg"), w) for w, _, j in TIERS if j))


if __name__ == "__main__":
    main()
