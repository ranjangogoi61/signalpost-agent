"""Rate probe for the Regnskapsregisteret account-copies endpoint: status codes only."""
import collections, time, urllib.request, urllib.error
ORGS = ["923609016", "914778271", "985589003", "935095190", "997830792", "916240257"]
UA = {"User-Agent": "signalpost-agent/1.0 (+https://github.com/ranjangogoi61/signalpost-agent)", "Accept": "application/json"}

def hit(org):
    req = urllib.request.Request(f"https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/aar", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)
    except Exception as e:
        return type(e).__name__, {}

for gap in (1.0, 0.5, 0.25):
    counts = collections.Counter(); first429 = None; t0 = time.time(); hdrs = set()
    for i in range(60):
        s, h = hit(ORGS[i % len(ORGS)])
        counts[s] += 1
        hdrs |= {k for k in h if "rate" in k.lower() or "retry" in k.lower() or "limit" in k.lower()}
        if s == 429 and first429 is None: first429 = i
        time.sleep(gap)
    print(f"gap={gap}s n=60 elapsed={time.time()-t0:.0f}s statuses={dict(counts)} first_429_at={first429} rate_headers={sorted(hdrs)}")
    time.sleep(75)
