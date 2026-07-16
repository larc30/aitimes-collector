# -*- coding: utf-8 -*-
"""
AI타임스 기사목록 수집기 v2 (EDCF 주간픽용)
- 매일 실행: 목록 페이지를 긁어 기존 articles.json에 '누적 병합'
- 최근 10일치만 유지 → 일주일 스캔 완전 커버 (페이지네이션 불필요)
- 외부 API 없음. 비용 0원.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

BASE = "https://www.aitimes.com"
LIST_URL = BASE + "/news/articleList.html?page={page}&view_type=sm"
MAX_PAGES = 3          # 매일 돌므로 1~3페이지면 충분 (2페이지부터 막혀도 무방)
KEEP_DAYS = 10
KST = timezone(timedelta(hours=9))
DATE_RE = re.compile(r"(\d{2})-(\d{2})\s+(\d{2}):(\d{2})")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Cache-Control": "no-cache",
}


def parse_date(text, now):
    m = DATE_RE.search(text)
    if not m:
        return None
    month, day, hh, mm = map(int, m.groups())
    year = now.year
    if month > now.month + 1:   # 연초에 12월 기사 읽는 경우 보정
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
        if not a or not a.get("href") or "articleView" not in a.get("href", ""):
            continue
        url = a["href"] if a["href"].startswith("http") else BASE + a["href"]
        title = a.get_text(strip=True)

        full_text = li.get_text(" ", strip=True)
        dt = parse_date(full_text, now)

        # 섹션명: em/span 중 날짜 패턴도 아니고 '기자'도 아닌 첫 텍스트
        section = ""
        for em in li.select("em, span"):
            t = em.get_text(strip=True)
            if not t or DATE_RE.search(t) or t.endswith("기자") or len(t) > 20:
                continue
            section = t
            break

        lead_el = li.select_one("p.lead, .lead")
        lead = lead_el.get_text(" ", strip=True)[:150] if lead_el else ""

        items.append({
            "title": title,
            "url": url,
            "date": dt.strftime("%Y-%m-%d %H:%M") if dt else "",
            "section": section,
            "lead": lead,
        })
    return items


def load_existing():
    if not os.path.exists("articles.json"):
        return {}
    try:
        with open("articles.json", encoding="utf-8") as f:
            data = json.load(f)
        return {it["url"]: it for it in data.get("items", [])}
    except Exception as e:
        print(f"[warn] 기존 파일 로드 실패, 새로 시작: {e}", file=sys.stderr)
        return {}


def main():
    now = datetime.now(KST)
    cutoff = now - timedelta(days=KEEP_DAYS)
    merged = load_existing()
    prev_count = len(merged)
    new_count = 0

    for page in range(1, MAX_PAGES + 1):
        try:
            r = requests.get(LIST_URL.format(page=page), headers=HEADERS, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print(f"[warn] page {page} fetch 실패: {e}", file=sys.stderr)
            continue
        items = parse_list_page(r.text, now)
        print(f"[info] page {page}: {len(items)}건 파싱")
        for it in items:
            if it["url"] not in merged:
                new_count += 1
            # 새 정보가 더 충실하면 갱신 (섹션·리드 보강)
            old = merged.get(it["url"], {})
            merged[it["url"]] = {
                "title": it["title"] or old.get("title", ""),
                "url": it["url"],
                "date": it["date"] or old.get("date", ""),
                "section": it["section"] or old.get("section", ""),
                "lead": it["lead"] or old.get("lead", ""),
            }

    # 기간 밖 제거
    def in_range(it):
        if not it["date"]:
            return True  # 날짜 파싱 실패분은 일단 보존
        dt = datetime.strptime(it["date"], "%Y-%m-%d %H:%M").replace(tzinfo=KST)
        return dt >= cutoff

    final = sorted(
        [it for it in merged.values() if in_range(it)],
        key=lambda x: x["date"], reverse=True,
    )

    with open("articles.json", "w", encoding="utf-8") as f:
        json.dump(
            {"generated": now.strftime("%Y-%m-%d %H:%M KST"),
             "count": len(final), "items": final},
            f, ensure_ascii=False, indent=1,
        )

    lines = [
        f"# AI타임스 최근 {KEEP_DAYS}일 기사 목록",
        f"- 수집 시각: {now.strftime('%Y-%m-%d %H:%M')} KST / 총 {len(final)}건 (이번 실행 신규 {new_count}건)",
        "",
    ]
    for it in final:
        sec = f"[{it['section']}] " if it["section"] else ""
        lines.append(f"- {it['date']} | {sec}{it['title']}")
        lines.append(f"  {it['url']}")
        if it["lead"]:
            lines.append(f"  · {it['lead']}")
    with open("articles.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[info] 저장 완료: 총 {len(final)}건 (기존 {prev_count} → 신규 +{new_count})")
    if len(final) == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
