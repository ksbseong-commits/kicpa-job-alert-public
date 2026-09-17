# -*- coding: utf-8 -*-
import hashlib
import html
import http.cookiejar
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime

STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def email_fingerprint(email: str) -> str:
    """재게시 판정은 '같은 이메일인가' 비교만 하면 되므로, 원문 대신 해시를 저장한다.
    이 저장소는 공개이므로 수집된 채용담당자 이메일을 평문으로 남기지 않는다."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()

SOURCES = {
    "cpa": {
        "list_url": "https://www.kicpa.or.kr/home/jobOffrSrchGnrl/list.face?ijJobSep=1&listCnt=30",
        "detail_url": "https://www.kicpa.or.kr/home/jobOffrSrchGnrl/detail.face?ijIdNum={}",
        "label": "구인(CPA)",
    },
    "new_cpa": {
        "list_url": "https://www.kicpa.or.kr/home/jobOffrSrchNewGnrl/list.face?listCnt=30&ijEmpSep=all",
        "detail_url": "https://www.kicpa.or.kr/home/jobOffrSrchNewGnrl/detail.face?ijIdNum={}",
        "label": "구인(수습CPA)",
    },
}

# 입사지원 메일 제목/본문은 개인정보(실명·경력·고객사명)라 코드에 두지 않고 GitHub Secrets로 주입한다.
FIXED_MAIL_SUBJECT = os.environ.get("MAIL_SUBJECT", "")
FIXED_MAIL_BODY = os.environ.get("MAIL_BODY", "")

TELEGRAM_API = "https://api.telegram.org/bot{}/sendMessage"


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def http_post_form(url, data: dict, headers=None):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_list(page_html):
    """반환: (게시글번호, 제목, 등록일자 or None) 목록"""
    anchor_re = re.compile(
        r"onclick=\"javascript:fn_detail\('(\d+)'\)\"\s*href=\"#\"\s*>\s*(.*?)\s*</a>",
        re.DOTALL,
    )
    date_re = re.compile(r"<td>(\d{4}\.\d{2}\.\d{2})</td>")

    matches = list(anchor_re.finditer(page_html))
    items = []
    for i, m in enumerate(matches):
        bltn_no = m.group(1)
        title = re.sub(r"\s+", " ", m.group(2)).strip()
        chunk_end = matches[i + 1].start() if i + 1 < len(matches) else len(page_html)
        chunk = page_html[m.end():chunk_end]
        date_m = date_re.search(chunk)
        reg_date = date_m.group(1) if date_m else None
        items.append((bltn_no, title, reg_date))
    return items


def is_recent(reg_date_str, days=3):
    """등록일자를 못 읽었으면 안전하게 통과(True)시킨다."""
    if not reg_date_str:
        return True
    try:
        d = datetime.strptime(reg_date_str, "%Y.%m.%d")
    except ValueError:
        return True
    return (datetime.now() - d).days <= days


def extract_pre_text(html):
    m = re.search(r'<pre[^>]*>(.*?)</pre>', html, re.DOTALL)
    if not m:
        return ""
    raw = m.group(1)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = re.sub(r"&nbsp;?", " ", raw)
    raw = re.sub(r"&amp;", "&", raw)
    return raw.strip()


def extract_deadline(html):
    m = re.search(r'마감일</th>\s*<td[^>]*>\s*([^<]+?)\s*</td>', html)
    if m:
        return m.group(1).strip()
    return "상세 참조"


def content_hash(body_text, deadline):
    """같은 게시글 ID라도 본문이나 마감일이 바뀌면(제자리 수정) 값이 달라진다."""
    return hashlib.sha256((body_text + "\n" + deadline).encode("utf-8")).hexdigest()


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def extract_email(text):
    emails = EMAIL_RE.findall(text)
    emails = list(dict.fromkeys(emails))  # dedupe, keep order
    if not emails:
        return ""
    if len(emails) == 1:
        return emails[0]
    # 여러 개면 '제출'/'접수'/'지원방법' 인접 이메일을 우선
    for kw in ["제출", "접수", "지원방법", "이메일"]:
        idx = text.find(kw)
        if idx == -1:
            continue
        window = text[idx:idx + 300]
        found = EMAIL_RE.findall(window)
        found = list(dict.fromkeys(found))
        if len(found) == 1:
            return found[0]
    # 애매하면 빈칸
    return ""


def build_mail_url(to_email):
    body_html = FIXED_MAIL_BODY.replace("\n", "<br>")
    params = {"subject": FIXED_MAIL_SUBJECT, "body": body_html}
    if to_email:
        params["to"] = to_email
    return "https://mail.naver.com/write/popup/?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def send_telegram_message(text, buttons):
    """buttons: list of (label, url), one button per row."""
    url = TELEGRAM_API.format(os.environ["TELEGRAM_BOT_TOKEN"])
    reply_markup = {"inline_keyboard": [[{"text": label, "url": link}] for label, link in buttons]}
    http_post_form(
        url,
        {
            "chat_id": os.environ["TELEGRAM_CHAT_ID"],
            "text": text,
            "reply_markup": json.dumps(reply_markup, ensure_ascii=False),
        },
    )


# ---- 삼일/삼정/안진: 제목+링크만 가져오는 간단 소스 ----

def fetch_pwc():
    page_html = http_get("https://www.pwc.com/kr/ko/career/experienced.html")
    m = re.search(r"Job title.*?</table>", page_html, re.DOTALL)
    if not m:
        return []
    table = m.group(0)
    items = []
    for tm in re.finditer(r'<tr><td><a href="([^"]+)">([^<]+)</a></td>', table):
        href, title = tm.group(1), html.unescape(tm.group(2).strip())
        url = href if href.startswith("http") else "https://www.pwc.com" + href
        idm = re.search(r"/(r[\d-]+)\.html", href)
        item_id = idm.group(1) if idm else href
        items.append((item_id, title, url, None))
    return items


def fetch_deloitte():
    page_html = http_get("https://join.deloitte.co.kr/WiseRecruit2/User/RecruitList.aspx?OrgOption=10")
    items = []
    pattern = re.compile(
        r'<a href="RecruitView\.aspx\?ridx=(\d+)" class="subject">\s*<span id="spanSubject">([^<]+)</span>',
        re.DOTALL,
    )
    for m in pattern.finditer(page_html):
        ridx, title = m.group(1), html.unescape(m.group(2).strip())
        url = f"https://join.deloitte.co.kr/WiseRecruit2/User/RecruitView.aspx?ridx={ridx}"
        items.append((ridx, title, url, None))
    return items


KPMG_LIST_URL = "https://career.kr.kpmg.com/hr/rec/recruit/jobopen/controller/candidate/JobOpen310WebController/init.hr"
KPMG_SEARCH_URL = "https://career.kr.kpmg.com/hr/rec/recruit/jobopen/controller/candidate/JobOpen310WebController/search.hr"


def fetch_kpmg():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(KPMG_LIST_URL, headers={"User-Agent": UA})
    opener.open(req, timeout=20).read()

    body = urllib.parse.urlencode(
        {
            "maxresults": "50",
            "maxlinks": "10",
            "currentpage": "1",
            "tab_receive_div_cd": "",
            "receive_div_cd": "",
            "jobopen_id": "",
            "sortType": "",
        }
    ).encode("utf-8")
    req = urllib.request.Request(KPMG_SEARCH_URL, data=body, method="POST", headers={"User-Agent": UA})
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    page_html = opener.open(req, timeout=20).read().decode("utf-8", errors="replace")

    items = []
    pattern = re.compile(
        r"goDetailPage\('([^']+)',\s*'[^']*'\).*?<p class=\"tit\">([^<]+)</p>",
        re.DOTALL,
    )
    for m in pattern.finditer(page_html):
        job_id, title = m.group(1), html.unescape(re.sub(r"\s+", " ", m.group(2)).strip())
        items.append((job_id, title, KPMG_LIST_URL, None))
    return items


def fetch_ey():
    # eycareers-kr.recruiter.co.kr는 순수 클라이언트 렌더링이라 직접 긁으면 빈 페이지만 나옴.
    # r.jina.ai(무료 JS 렌더링 프록시)를 통해 렌더링된 결과를 대신 받아온다.
    target = "https://eycareers-kr.recruiter.co.kr/career/career"
    req = urllib.request.Request(
        "https://r.jina.ai/" + target,
        headers={"User-Agent": UA, "x-no-cache": "true"},
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        text = resp.read().decode("utf-8", errors="replace")

    items = []
    pattern = re.compile(r"\*\s+\[(.*?)\]\(https://eycareers-kr\.recruiter\.co\.kr/career/jobs/(\d+)\)")
    date_split_re = re.compile(r"\s+(?:D-(?:Day|\d+)\s+)?(\d{4}\.\d{2}\.\d{2})")
    for m in pattern.finditer(text):
        raw, job_id = m.group(1), m.group(2)
        parts = date_split_re.split(raw, maxsplit=1)
        title = re.sub(r"^(접수중|마감임박)\s*", "", parts[0]).strip()
        # parts[1]이 있으면 접수 시작일(=등록일 근사치); 없으면(상시채용 등) 최근으로 간주
        reg_date = parts[1] if len(parts) > 1 else None
        url = f"https://eycareers-kr.recruiter.co.kr/career/jobs/{job_id}"
        items.append((job_id, title, url, reg_date))
    return items


SIMPLE_SOURCES = {
    "pwc": {"fetch": fetch_pwc, "label": "삼일회계법인"},
    "deloitte": {"fetch": fetch_deloitte, "label": "안진회계법인"},
    "kpmg": {"fetch": fetch_kpmg, "label": "삼정회계법인"},
    "ey": {"fetch": fetch_ey, "label": "한영회계법인(EY)"},
}


EDIT_SCAN_INTERVAL_SECONDS = 3600  # 크론이 1분마다 돌아도, 이미 본 글의 '내용 수정' 재확인은 이 주기로만 한다


def main():
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)

    sent_count = 0
    known_emails = set(state.get("known_emails", []))
    edit_scan_state = state.setdefault("last_edit_scan", {})

    for source_key, cfg in SOURCES.items():
        seen = set(state["seen"].get(source_key, []))
        hashes = state.setdefault("content_hash", {}).setdefault(source_key, {})
        reg_dates = state.setdefault("reg_dates", {}).setdefault(source_key, {})
        try:
            list_html = http_get(cfg["list_url"])
        except Exception as e:
            print(f"[{source_key}] list fetch failed: {e}", file=sys.stderr)
            continue

        items = parse_list(list_html)

        priming = len(seen) == 0
        if priming:
            print(f"[{source_key}] priming: marking {len(items)} existing postings as seen (no notify)")
            for bid, _, reg_date in items:
                seen.add(bid)
                reg_dates[bid] = reg_date
            state["seen"][source_key] = sorted(seen)
            continue

        last_scan_str = edit_scan_state.get(source_key)
        last_scan = None
        if last_scan_str:
            try:
                last_scan = datetime.fromisoformat(last_scan_str)
            except ValueError:
                last_scan = None
        now = datetime.utcnow()
        do_edit_scan = last_scan is None or (now - last_scan).total_seconds() >= EDIT_SCAN_INTERVAL_SECONDS

        # 신규 글은 매번 확인한다. 이미 본 글까지 상세를 다시 읽어 '내용 수정' 여부를
        # 대조하는 건 do_edit_scan일 때만 — 크론이 1분마다 돌아도 KICPA 상세페이지
        # 재조회는 시간당 최대 목록 크기(약 30건)만큼만 발생하도록 막는다.
        # 단, 목록의 등록일자가 갱신되는 '재게시'는 상세 조회 없이도 감지되므로
        # (list_html은 어차피 매번 받아온다) do_edit_scan과 무관하게 즉시 잡는다.
        for bid, title, reg_date in reversed(items):  # 오래된 순으로 처리
            is_new = bid not in seen
            seen.add(bid)
            if is_new and not is_recent(reg_date):
                print(f"[{source_key}] skip old posting (reg_date={reg_date}): {title} ({bid})")
                continue

            prev_reg_date = reg_dates.get(bid)
            reg_dates[bid] = reg_date
            is_reposted = not is_new and bool(reg_date) and bool(prev_reg_date) and reg_date != prev_reg_date

            if not is_new and not is_reposted and not do_edit_scan:
                continue

            detail_url = cfg["detail_url"].format(bid)
            try:
                detail_html = http_get(detail_url)
            except Exception as e:
                print(f"[{source_key}] detail fetch failed for {bid}: {e}", file=sys.stderr)
                continue

            body_text = extract_pre_text(detail_html)
            deadline = extract_deadline(detail_html)
            new_hash = content_hash(body_text, deadline)
            old_hash = hashes.get(bid)
            hashes[bid] = new_hash

            if is_new:
                kind = "new"
            elif is_reposted:
                kind = "reposted"
            elif old_hash is not None and old_hash != new_hash:
                kind = "edited"
            else:
                # 변화 없음, 또는 이번이 이 ID에 대한 첫 해시 기록(기준값만 세우고 알림 없음)
                continue

            email = extract_email(body_text)
            mail_url = build_mail_url(email)

            if kind == "new":
                is_repost = bool(email) and email_fingerprint(email) in known_emails
                repost_tag = "[재게시] " if is_repost else ""
            elif kind == "reposted":
                repost_tag = "[재게시] "
            else:
                repost_tag = "[수정] "
            if email:
                known_emails.add(email_fingerprint(email))

            text = f"[{cfg['label']}] {repost_tag}{title}\n마감일: {deadline}\n\n" + body_text[:3500]

            buttons = [("공고 원문 보기", detail_url), ("메일로 보내기", mail_url)]
            try:
                send_telegram_message(text, buttons)
                sent_count += 1
                print(f"[{source_key}] sent ({kind}): {title} ({bid})")
            except Exception as e:
                print(f"[{source_key}] telegram send failed for {bid}: {e}", file=sys.stderr)

        state["seen"][source_key] = sorted(seen)
        state["content_hash"][source_key] = hashes
        state["reg_dates"][source_key] = reg_dates
        if do_edit_scan:
            edit_scan_state[source_key] = now.isoformat()

    for source_key, cfg in SIMPLE_SOURCES.items():
        seen = set(state["seen"].get(source_key, []))
        try:
            items = cfg["fetch"]()
        except Exception as e:
            print(f"[{source_key}] fetch failed: {e}", file=sys.stderr)
            continue

        new_items = [(iid, title, url, reg_date) for iid, title, url, reg_date in items if iid not in seen]

        priming = len(seen) == 0
        if priming:
            print(f"[{source_key}] priming: marking {len(items)} existing postings as seen (no notify)")
            for iid, _, _, _ in items:
                seen.add(iid)
            state["seen"][source_key] = sorted(seen)
            continue

        for iid, title, url, reg_date in reversed(new_items):
            seen.add(iid)
            if not is_recent(reg_date):
                print(f"[{source_key}] skip old posting (reg_date={reg_date}): {title} ({iid})")
                continue
            text = f"[{cfg['label']}] {title}"
            try:
                send_telegram_message(text, [("공고 보기", url)])
                sent_count += 1
                print(f"[{source_key}] sent: {title} ({iid})")
            except Exception as e:
                print(f"[{source_key}] telegram send failed for {iid}: {e}", file=sys.stderr)

        state["seen"][source_key] = sorted(seen)

    state["known_emails"] = sorted(known_emails)

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print(f"done. sent={sent_count}")


if __name__ == "__main__":
    main()
