# -*- coding: utf-8 -*-
"""임시 샘플 발송용. state.json을 건드리지 않고, 현재 게시판의 공고 1건을 실제 알림과 같은 형식으로 보낸다."""
import sys

import scraper

cfg = scraper.SOURCES["cpa"]
items = scraper.parse_list(scraper.http_get(cfg["list_url"]))
print(f"list items: {len(items)}")

pick = None
for bid, title, reg_date in items[:15]:
    detail_url = cfg["detail_url"].format(bid)
    detail_html = scraper.http_get(detail_url)
    body_text = scraper.extract_pre_text(detail_html)
    email = scraper.extract_email(body_text)
    if email:
        pick = (bid, title, detail_url, detail_html, body_text, email)
        break
if not pick:
    sys.exit("이메일이 있는 공고를 찾지 못함")

bid, title, detail_url, detail_html, body_text, email = pick
deadline = scraper.extract_deadline(detail_html)
mail_url = scraper.build_mail_url(email)
print(f"mail url length: {len(mail_url)} (limit ~4900)")  # 본문은 로그에 남기지 않는다
text = f"[{cfg['label']}] [샘플] {title}\n마감일: {deadline}\n\n" + body_text[:3500]
scraper.send_telegram_message(text, [("공고 원문 보기", detail_url), ("메일로 보내기", mail_url)])
print(f"sample sent: {title} ({bid})")
