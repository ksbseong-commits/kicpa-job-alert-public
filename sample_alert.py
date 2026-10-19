# -*- coding: utf-8 -*-
"""임시 길이 테스트용. state.json을 건드리지 않는다. 링크 길이를 정확히 맞춰 버튼이 열리는 한계를 찾는다."""
import sys
import urllib.parse

import scraper

cfg = scraper.SOURCES["cpa"]
items = scraper.parse_list(scraper.http_get(cfg["list_url"]))
pick = None
for bid, title, reg_date in items[:15]:
    detail_url = cfg["detail_url"].format(bid)
    body_text = scraper.extract_pre_text(scraper.http_get(detail_url))
    email = scraper.extract_email(body_text)
    if email:
        pick = (title, email)
        break
if not pick:
    sys.exit("이메일이 있는 공고를 찾지 못함")
title, email = pick


def url_for(body):
    params = {"subject": scraper.FIXED_MAIL_SUBJECT, "body": body.replace("\n", "<br>"), "to": email}
    return "https://mail.naver.com/write/popup/?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


for target in (4400, 4500, 4600, 4700):
    body = "길이 테스트 본문입니다. "
    while len(url_for(body + "x")) <= target:
        body += "x"
    u = url_for(body)
    print(f"target {target}: url length {len(u)}")
    scraper.send_telegram_message(f"[길이 테스트] 링크 {len(u)}자", [(f"{len(u)}자", u)])
print("done")
