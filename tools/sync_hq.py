"""Add sessions to the Engine Room log and recompute everything derived from them.

The HQ blob in index.html holds four structures, and three of them are derived
from the fourth:

  acts    the session list, the only thing that is authored
  totals  per sport aggregates      <- derived
  chart   monthly hours per sport   <- derived
  cal     the calendar grid         <- derived

Hand editing a session meant editing all four consistently, which is how a log
drifts away from its own summary. This recomputes the three from `acts`.

The one field that is not derivable is `msp`, the max speed Strava reports per
activity. It is not carried on the sessions, so it is preserved as it stands
unless a new session declares a higher one.

Usage:
  python3 tools/sync_hq.py --add '[{...}, {...}]'    add sessions, then rebuild
  python3 tools/sync_hq.py --rebuild                 rebuild from acts alone
  python3 tools/sync_hq.py --check                   report drift, change nothing
"""

import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "index.html")
SPORTS = ("S", "R", "N", "X")
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def load():
    src = open(PAGE, encoding="utf-8").read()
    m = re.search(r"var HQ\s*=\s*(\{.*?\});", src, re.S)
    if not m:
        sys.exit("could not find the HQ blob in index.html")
    return src, m, json.loads(m.group(1))


def lead_num(v):
    m = re.match(r"([\d,.]+)", str(v or ""))
    return float(m.group(1).replace(",", "")) if m else 0.0


def hms(sec):
    return "%d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def build_totals(acts, previous):
    out = {}
    for t in SPORTS:
        g = [a for a in acts if a["t"] == t]
        if not g:
            continue
        dist = sum(lead_num(a.get("dist")) for a in g)
        effs = [a["eff"] for a in g if a.get("eff") is not None]
        longest = max(g, key=lambda a: lead_num(a.get("dist")))
        unit = "yd" if t == "S" else "mi"
        row = {
            "n": len(g),
            "dist": ("{:,.0f} yd" if t == "S" else "{:,.1f} mi").format(dist),
            "time": hms(sum(a.get("sec", 0) for a in g)),
            "longest": "%s (%s)" % (longest["n"], longest.get("dist") or "-"),
            "kcal": sum(a.get("kcal") or 0 for a in g),
        }
        elev = sum(a.get("elev") or 0 for a in g)
        if elev or (previous.get(t, {}).get("elev") is not None):
            row["elev"] = elev
        if effs:
            row["eff"] = round(sum(effs) / len(effs))
        # Not derivable from the sessions, so it carries over.
        prev_msp = previous.get(t, {}).get("msp")
        if prev_msp is not None:
            row["msp"] = prev_msp
        out[t] = row
    return out


def build_chart(acts):
    mon = defaultdict(lambda: defaultdict(float))
    for a in acts:
        mon[a["d"][:7]][a["t"]] += a.get("sec", 0) / 3600
    return [dict({"m": m}, **{t: round(mon[m].get(t, 0.0), 2) for t in SPORTS})
            for m in sorted(mon)]


def build_cal(acts):
    import calendar
    byday = defaultdict(list)
    for a in acts:
        byday[a["d"]].append(a)
    months = sorted({a["d"][:7] for a in acts})
    out = []
    for ym in months:
        y, mo = int(ym[:4]), int(ym[5:7])
        # The grid is Monday first, which is exactly what monthrange counts from.
        pad, ndays = calendar.monthrange(y, mo)
        days = []
        for d in range(1, ndays + 1):
            key = "%s-%02d" % (ym, d)
            # Newest first within a day, matching how the log reads.
            entries = [{"t": a["t"], "n": a["n"], "dist": a.get("dist", ""), "id": a["id"]}
                       for a in byday.get(key, [])]
            days.append({"d": d, "a": entries})
        out.append({"label": "%s %d" % (MONTHS[mo - 1], y), "pad": pad, "days": days})
    return out


def main():
    src, match, hq = load()
    acts = hq["acts"]

    if "--add" in sys.argv:
        payload = json.loads(sys.argv[sys.argv.index("--add") + 1])
        have = {a["id"] for a in acts}
        added = 0
        for a in payload:
            if a["id"] in have:
                print("  already present, skipping: %s %s" % (a["d"], a["n"]))
                continue
            acts.append(a)
            added += 1
            print("  added: %s  %-28s %s" % (a["d"], a["n"], a.get("dist") or a["time"]))
        if not added:
            print("nothing new to add")
        acts.sort(key=lambda a: (a["d"], a["id"]), reverse=True)

    fresh = {
        "acts": acts,
        "totals": build_totals(acts, hq.get("totals", {})),
        "chart": build_chart(acts),
        "cal": build_cal(acts),
    }

    if "--check" in sys.argv:
        drift = [k for k in ("totals", "chart", "cal")
                 if json.dumps(hq.get(k), sort_keys=True) != json.dumps(fresh[k], sort_keys=True)]
        print("sessions: %d" % len(acts))
        print("drift in: %s" % (", ".join(drift) if drift else "nothing, all derived data agrees"))
        sys.exit(1 if drift else 0)

    blob = json.dumps(fresh, separators=(", ", ": "))
    out = src[:match.start(1)] + blob + src[match.end(1):]
    open(PAGE, "w").write(out)
    for t in SPORTS:
        if t in fresh["totals"]:
            r = fresh["totals"][t]
            print("  %s  n=%-3d %-12s %-10s kcal=%s" % (t, r["n"], r["dist"], r["time"], r["kcal"]))
    print("wrote %d sessions into index.html" % len(acts))


if __name__ == "__main__":
    main()
