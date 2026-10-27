"""Shape probe for candidate open registers: status, size, first tags/columns, sample field names. No row values."""
import io, json, re, sys, time, urllib.request, urllib.parse, gzip
UA = {"User-Agent": "signalpost-agent/1.0 (+https://github.com/ranjangogoi61/signalpost-agent)"}

def get(url, limit=80_000_000, headers=None, data=None):
    t = time.time()
    req = urllib.request.Request(url, headers={**UA, **(headers or {})}, data=data)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read(limit + 1)
            return r.status, raw, r.headers.get("content-type"), round(time.time() - t, 1)
    except Exception as e:
        return str(e)[:120], b"", None, round(time.time() - t, 1)

def digits9(s): return len(set(re.findall(rb"(?<!\d)[89]\d{8}(?!\d)", s)))

for name, url in [
    ("renhold", "https://registerdata.arbeidstilsynet.no/renhold_register.xml"),
    ("bht", "https://registerdata.arbeidstilsynet.no/bht_register.xml"),
    ("bemanning", "https://data.arbeidstilsynet.no/bemanningsforetaksregisteret2/api"),
    ("bilpleie", "https://data.arbeidstilsynet.no/bilpleieregisteret/api"),
    ("smilefjes", "https://smilefjes.mattilsynet.no/api/tilsyn.csv"),
]:
    st, raw, ct, secs = get(url)
    print(f"== {name}: status={st} type={ct} bytes={len(raw)} secs={secs} distinct_orgnr_like={digits9(raw)}")
    head = raw[:4000].decode("utf-8", "replace")
    if "xml" in str(ct) or head.lstrip().startswith("<"):
        tags = list(dict.fromkeys(re.findall(r"<([A-Za-z_][\w:.-]*)", raw[:200000].decode("utf-8", "replace"))))[:60]
        print("   tags:", tags)
    elif "json" in str(ct) or head.lstrip()[:1] in "[{":
        try:
            d = json.loads(raw)
            def keys(v, depth=0):
                if depth > 3: return "…"
                if isinstance(v, dict): return {k: keys(x, depth + 1) for k, x in list(v.items())[:30]}
                if isinstance(v, list): return [keys(v[0], depth + 1)] if v else []
                return type(v).__name__
            print("   json:", json.dumps(keys(d))[:2500])
        except Exception as e:
            print("   json error", e, head[:300].replace("\n", " ")[:0])
    else:
        print("   header:", head.splitlines()[0][:600] if head else "")

q = '[out:json][timeout:120];area["ISO3166-1"="NO"][admin_level=2]->.no;nwr["ref:NO:orgnr"](area.no);out tags;'
st, raw, ct, secs = get("https://overpass-api.de/api/interpreter", data=urllib.parse.urlencode({"data": q}).encode())
try:
    els = json.loads(raw).get("elements", [])
    with_site = sum(1 for e in els if (e.get("tags") or {}).get("website") or (e.get("tags") or {}).get("contact:website"))
    print(f"== overpass: status={st} secs={secs} bytes={len(raw)} elements={len(els)} with_website={with_site}")
except Exception as e:
    print(f"== overpass: status={st} secs={secs} error={e}")
st, raw, ct, secs = get("https://rdap.norid.no/norid_domain_count/923609016")
print(f"== norid_domain_count: status={st} secs={secs} body_keys={list(json.loads(raw).keys())[:10] if raw.startswith(b'{') else raw[:80]}")
