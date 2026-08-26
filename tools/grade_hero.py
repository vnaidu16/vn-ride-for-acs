"""Hero grading pipeline, matching the look documented in CLAUDE.md.

desat .92, contrast 1.16, brightness .92, cool shadows (r-6, b*1.06+6),
bloom via blurred-highlight screen blend, grain, vignette.

Usage: grade.py <in.jpg> <out.jpg> [width] [--no-grain]
"""
import sys

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps


def grade(im, width, grain=True):
    im = ImageOps.exif_transpose(im).convert("RGB")
    if width and im.width != width:
        h = round(im.height * width / im.width)
        im = im.resize((width, h), Image.LANCZOS)

    im = ImageEnhance.Color(im).enhance(0.92)
    im = ImageEnhance.Contrast(im).enhance(1.16)
    im = ImageEnhance.Brightness(im).enhance(0.92)

    # cool the shadows
    r, g, b = im.split()
    r = r.point(lambda v: max(0, v - 6))
    b = b.point(lambda v: min(255, int(v * 1.06 + 6)))
    im = Image.merge("RGB", (r, g, b))

    # bloom: isolate highlights, blur them, screen back over the frame
    hi = im.point(lambda v: 0 if v < 170 else min(255, (v - 170) * 3))
    hi = hi.filter(ImageFilter.GaussianBlur(im.width * 0.012))
    im = Image.blend(im, ImageChops.screen(im, hi), 0.42)

    # light unsharp so the downsample keeps its edges
    im = im.filter(ImageFilter.UnsharpMask(radius=1.4, percent=62, threshold=3))

    if grain:
        noise = Image.effect_noise(im.size, 5).convert("L")
        noise = Image.merge("RGB", (noise, noise, noise))
        im = ImageChops.add(im, noise, scale=1.0, offset=-128)

    return apply_vignette(im, 0.42)


def apply_vignette(im, strength):
    """Radial falloff built small and scaled up, which is fast and smooth."""
    w, h = im.size
    sw, sh = 160, max(1, round(160 * h / w))
    mask = Image.new("L", (sw, sh))
    px = mask.load()
    cx, cy = sw / 2.0, sh / 2.0
    inner = min(sw, sh) * 0.28
    outer = max(sw, sh) * 0.72
    for y in range(sh):
        dy = (y - cy) ** 2
        for x in range(sw):
            d = (dy + (x - cx) ** 2) ** 0.5
            t = 0.0 if d <= inner else min(1.0, (d - inner) / (outer - inner))
            px[x, y] = int(255 * t * strength)
    mask = mask.resize((w, h), Image.BICUBIC)
    return Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), im, mask)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src, dst = args[0], args[1]
    wid = int(args[2]) if len(args) > 2 else 1800
    out = grade(Image.open(src), wid, grain="--no-grain" not in sys.argv)
    out.save(dst, "JPEG", quality=90, optimize=True, progressive=True)
    print("%s -> %s  %dx%d  %d bytes" % (
        src, dst, out.width, out.height, len(out.tobytes()) // 1024))
