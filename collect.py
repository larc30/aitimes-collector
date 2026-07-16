# -*- coding: utf-8 -*-
"""
AI타임스 기사목록 수집기 (EDCF 주간픽용)
- articleList.html 1~N페이지를 긁어 최근 10일 기사 목록을 저장
- 출력: articles.md (사람/Claude가 읽는 용도), articles.json (백업)
- 외부 API 없음. 비용 0원.
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

BASE = "https://www.aitimes.com"
LIST_URL = BASE + "/news/articleList.html?page={page}&view_type=sm"
MAX_PAGES = 8          # 20건/페이지 × 8 = 최대 160건
KEEP_DAYS = 10         # 최근 10일치만 저장 (주간픽 기간을 넉넉히 커버)
KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Cache-Control": "no-cache",
}


def parse_date(text, now):
    """'07-14 11:05' 형태를 KST datetime으로. 연말/연초 경계 처리."""
    m = re.search(r"(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", text)
    if not m:
        return None
    month, day, hh, mm = map(int, m.groups())
    year = now.year
    # 12월 기사 목록을 1월에 읽는 경우 등 경계 보정
    if month > now.month + 1:
        year -= 1
    try:
        return datetime(year, month, day, hh, mm, tzinfo=KST)
    except ValueError:
        return None


def parse_list_page(html, now):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    container = soup.select_one("#section-list") or soup
    for li in container.select("li"):
        a = li.select_one("h4 a, h2 a, .titles a")
        if not a or not a.get("href"):
            continue
        href = a["href"]
        if "articleView" not in href:
            continue
        url = href if href.startswith("http") else BASE + href
        title = a.get_text(strip=True)

        # 날짜: li 안의 텍스트에서 MM-DD HH:MM 패턴 탐색
        dt = parse_date(li.get_text(" ", strip=True), now)

        # 섹션명: 보통 첫 번째 em/span 류에 표시됨
        section = ""
        em = li.select_one("em, .byline em, .info span")
        if em:
            section = em.get_text(strip=True)

        # 리드문
        lead_el = li.select_one("p.lead, .lead, p")
        lead = lead_el.get_text(" ", strip=True)[:150] if lead_el else ""

        if title and url:
            items.append({
                "title": title,
                "url": url,
                "date": dt.strftime("%Y-%m-%d %H:%M") if dt else "",
                "section": section,
                "lead": lead,
            })
    return items


def main():
    now = datetime.now(KST)
    cutoff = now - timedelta(days=KEEP_DAYS)
    all_items, seen = [], set()
    stop = False

    for page in range(1, MAX_PAGES + 1):
        try:
            r = requests.get(LIST_URL.format(page=page), headers=HEADERS, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print(f"[warn] page {page} fetch 실패: {e}", file=sys.stderr)
            continue

        items = parse_list_page(r.text, now)
        if not items:
            print(f"[warn] page {page}: 파싱된 기사 0건 (구조 변경 가능성)", file=sys.stderr)
            continue

        for it in items:
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            # 기간 밖 기사가 나오기 시작하면 다음 페이지는 볼 필요 없음
            if it["date"]:
                dt = datetime.strptime(it["date"], "%Y-%m-%d %H:%M").replace(tzinfo=KST)
                if dt < cutoff:
                    stop = True
                    continue
            all_items.append(it)
        if stop:
            break

    all_items.sort(key=lambda x: x["date"], reverse=True)

    # JSON 저장
    with open("articles.json", "w", encoding="utf-8") as f:
        json.dump(
            {"generated": now.strftime("%Y-%m-%d %H:%M KST"), "count": len(all_items), "items": all_items},
            f, ensure_ascii=False, indent=1,
        )

    # Markdown 저장 (Claude가 읽는 파일)
    lines = [
        f"# AI타임스 최근 {KEEP_DAYS}일 기사 목록",
        f"- 수집 시각: {now.strftime('%Y-%m-%d %H:%M')} KST / 총 {len(all_items)}건",
        "",
    ]
    for it in all_items:
        lines.append(f"- {it['date']} | [{it['section']}] {it['title']}")
        lines.append(f"  {it['url']}")
        if it["lead"]:
            lines.append(f"  · {it['lead']}")
    with open("articles.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[info] 저장 완료: {len(all_items)}건")
    if len(all_items) == 0:
        sys.exit(1)  # 0건이면 워크플로 실패로 표시해 알아차리게 함


if __name__ == "__main__":
    main()
