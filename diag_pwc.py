import re, urllib.request, urllib.error

LIST = "https://www.pwc.com/kr/ko/career/experienced.html"
JOB = "https://www.pwc.com/kr/ko/career/experienced/r261007.html"
CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/126.0.0.0 Safari/537.36")
HEADER_SETS = {
    "current-UA": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
    "chrome-UA": {"User-Agent": CHROME},
    "chrome-full": {"User-Agent": CHROME, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"},
}

def get(url, headers):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return type(e).__name__, ""

for name, h in HEADER_SETS.items():
    for label, url in (("list", LIST), ("job", JOB)):
        for i in range(3):
            st, body = get(url, h)
            extra = ""
            if label == "list" and body:
                m = re.search(r"Job title.*?</table>", body, re.S)
                rows = re.findall(r'<tr><td><a href="([^"]+)">([^<]+)</a></td>', m.group(0)) if m else []
                ids = [re.search(r"/(r[\d-]+)\.html", a).group(1) for a, _ in rows if re.search(r"/(r[\d-]+)\.html", a)]
                extra = f"table={bool(m)} rows={len(rows)} has_r261007={'r261007' in body} newest_ids={ids[-6:]}"
                if 'r261007' in body:
                    i2 = body.index('r261007'); extra += f"\n  ctx: {body[max(0,i2-200):i2+200]!r}"
            if label == "job" and body:
                t = re.search(r"<title>([^<]*)", body)
                extra = f"title={t.group(1).strip() if t else None}"
            print(f"{name:12} {label:4} try{i+1} -> {st} len={len(body)} {extra}", flush=True)
