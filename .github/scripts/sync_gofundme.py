"""Refresh data.json from the live GoFundMe campaign.

Money fields only. The 'miles' field is manual and Strava verified,
so it is always carried over untouched. Fails closed: on any parse
problem or failed sanity check this exits non-zero and writes nothing.
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone

URL = ("https://www.gofundme.com/f/"
       "im-cycling-300-miles-for-the-american-cancer-society-m4djn")
DATA = "data.json"


def die(msg):
    print("sync failed: " + msg, file=sys.stderr)
    sys.exit(1)


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def fundraiser(html):
    m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        die("__NEXT_DATA__ block not found")
    try:
        blob = json.loads(m.group(1))
    except ValueError as e:
        die("__NEXT_DATA__ is not valid JSON: %s" % e)
    apollo = blob.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__")
    if not isinstance(apollo, dict):
        die("Apollo state missing")
    for key, val in apollo.items():
        if key.startswith("Fundraiser:") and isinstance(val, dict) \
                and "currentAmount" in val:
            return val
    die("no Fundraiser entry in Apollo state")


def amount(node, field):
    val = node.get(field)
    if isinstance(val, dict):
        val = val.get("amount")
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        die("field %s is not numeric: %r" % (field, val))
    return val


def main():
    try:
        old = json.load(open(DATA))
    except Exception as e:
        die("cannot read %s: %s" % (DATA, e))

    node = fundraiser(fetch())
    raised = amount(node, "currentAmount")
    goal = amount(node, "goalAmount")
    donors = node.get("donationCount")
    if not isinstance(donors, int) or isinstance(donors, bool):
        die("donationCount is not an integer: %r" % donors)

    prev = float(old.get("raised") or 0)
    if raised <= 0:
        die("raised is not positive: %r" % raised)
    if goal <= 0:
        die("goal is not positive: %r" % goal)
    if donors < 0:
        die("donors is negative: %r" % donors)
    # Refunds happen, but a collapse or an absurd spike means a bad parse.
    if prev > 0 and not (prev * 0.5 <= raised <= prev * 10 + 10000):
        die("raised %r is implausible next to previous %r" % (raised, prev))

    new = dict(old)
    new["raised"] = raised
    new["donors"] = donors
    new["goal"] = goal
    new["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # miles stays exactly as it was, never derived from GoFundMe.

    with open(DATA, "w") as f:
        json.dump(new, f, indent=2)
        f.write("\n")
    print("raised=%s donors=%s goal=%s" % (raised, donors, goal))


if __name__ == "__main__":
    main()
