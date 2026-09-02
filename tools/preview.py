"""Publish a throwaway copy of the site alongside the real one.

GitHub Pages serves a single branch, so a preview branch is not an option here.
What does work is a second file in the same folder: preview.html sits next to
index.html, which means every relative path in it (images, data.json) resolves
exactly as it does live. No <base> tag, no duplicated assets, no build step.

  python3 tools/preview.py            copy index.html -> preview.html
  python3 tools/preview.py --diff     show what differs, change nothing
  python3 tools/preview.py --clear    delete preview.html

Then commit and push as usual. It lands at:

  https://vnaidu16.github.io/vn-ride-for-acs/preview.html

Open that on a phone. That is the whole point: the layout on a real handset has
been the one thing that could never be checked before shipping.

Two things are injected so it can never be mistaken for the live page: a
noindex tag, so search engines and link scrapers ignore it, and a marker in the
corner. The live page is index.html and nothing here touches it.
"""

import difflib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "index.html")
PREV = os.path.join(ROOT, "preview.html")

MARK = """<meta name="robots" content="noindex, nofollow">
<style>
  #previewflag { position: fixed; left: 0; bottom: 0; z-index: 2147483647;
    font: 800 10px/1 -apple-system, 'SF Pro Display', sans-serif; letter-spacing: 1.6px;
    text-transform: uppercase; color: #06121a; background: #ffd23f;
    padding: 6px 10px; border-radius: 0 8px 0 0; pointer-events: none; }
</style>
"""

FLAG = '<div id="previewflag">Preview &middot; not the live page</div>'


def build():
    src = open(LIVE, encoding="utf-8").read()
    # noindex goes first in the head so a scraper sees it before anything else
    out = src.replace("<head>", "<head>\n" + MARK, 1)
    out = out.replace("</body>", FLAG + "\n</body>", 1)
    # The preview must never be the canonical target of a share card.
    out = re.sub(r'(<meta property="og:url" content=")[^"]*(")',
                 r"\1https://vnaidu16.github.io/vn-ride-for-acs/preview.html\2", out)
    open(PREV, "w").write(out)
    return src, out


def main():
    if "--clear" in sys.argv:
        if os.path.exists(PREV):
            os.remove(PREV)
            print("removed preview.html")
        else:
            print("nothing to remove")
        return

    if "--diff" in sys.argv:
        if not os.path.exists(PREV):
            sys.exit("no preview.html yet; run without --diff to make one")
        live = open(LIVE, encoding="utf-8").read()
        # Undo the injection rather than filter the diff by keyword: that way
        # anything left over is real drift and not this script's own marker.
        stripped = open(PREV, encoding="utf-8").read() \
            .replace("<head>\n" + MARK, "<head>", 1) \
            .replace(FLAG + "\n</body>", "</body>", 1)
        stripped = re.sub(r'(<meta property="og:url" content=")[^"]*(")',
                          r"\1https://vnaidu16.github.io/vn-ride-for-acs/\2", stripped)
        d = [x for x in difflib.unified_diff(live.splitlines(), stripped.splitlines(),
                                             "index.html", "preview.html", n=0)
             if x.startswith(("+", "-")) and not x.startswith(("+++", "---"))]
        if not d:
            print("preview.html matches index.html")
            return
        print("%d lines of real drift; re-run without --diff to refresh" % len(d))
        for line in d[:40]:
            print("  " + line[:140])
        return

    src, out = build()
    print("preview.html written, %.0f KB" % (len(out) / 1024))
    print("push, then open on a phone:")
    print("  https://vnaidu16.github.io/vn-ride-for-acs/preview.html")


if __name__ == "__main__":
    main()
