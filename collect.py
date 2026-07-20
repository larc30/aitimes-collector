# -*- coding: utf-8 -*-
"""
AI타임스 기사목록 수집기 v3 (EDCF 주간픽용)
- 매일 실행: 목록 페이지를 긁어 기존 articles.json에 '누적 병합'
- 최근 KEEP_DAYS일치만 유지 → 일주일 스캔 완전 커버
- v3 변경점:
  * 리드문 추출 보강: 목록 페이지에서 다중 셀렉터 시도 + 폴백
  * 목록에서 리드문 못 찾은 기사는 상세 페이지 meta-description에서 추출
    (실행당 DETAIL_FETCH_LIMIT건 제한 → 부하·차단 리스크 최소화)
  * KEEP_DAYS 10 → 15
- 외부 API 없음. 비용 0원.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

BASE = "https://www.aitimes.com"
LIST_URL = BASE + "/news/articleList.html?page={page}&view_type=sm"
MAX_PAGES = 3            # 매일 돌므로 1~3페이지면 충분 (2페이지부터 막혀도 무방)
KEEP_DAYS = 15           # 유지 기간 (주간픽 7일 + 여유)
DETAIL_FETCH_LIMIT = 15  # 실행당 상세 페이지 방문 상한 (리드문 폴백용)
DETAIL_FETCH_SLEEP = 1.0 # 상세 페이지 요청 간격(초)
LEAD_MAX_LEN = 200
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


def clean_lead(text):
    """리드문 정리: 공백 정규화, 길이 제한."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    # 목록에 붙는 말줄임 기호 제거
    text = text.rstrip("…").rstrip("...")
    return text[:LEAD_MAX_LEN]


def extract_lead_from_li(li, title):
    """목록 페이지 li 안에서 리드문 추출. 다중 셀렉터 → 폴백 순."""
    # 1) 알려진 클래스 후보 (ndsoft CMS 계열)
    for sel in ("p.lead a", "p.lead", ".lead", "p.sbody", ".article-summary", "p.summary"):
        el = li.select_one(sel)
        if el:
            t = clean_lead(el.get_text(" ", strip=True))
            if len(t) >= 20:
                return t
    # 2) 폴백: li 안의 <p> 중 가장 긴 텍스트 (제목과 다르고 20자 이상)
    best = ""
    for p in li.find_all("p"):
        t = clean_lead(p.get_text(" ", strip=True))
        if len(t) >= 20 and t != title and len(t) > len(best):
            best = t
    return best


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

        lead = extract_lead_from_li(li, title)

        items.append({
            "title": title,
            "url": url,
            "date": dt.strftime("%Y-%m-%d %H:%M") if dt else "",
            "section": section,
            "lead": lead,
        })
    return items


def fetch_lead_from_detail(url):
    """상세 페이지에서 meta-description 기반 리드문 추출 (폴백)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"[warn] 상세 fetch 실패 {url}: {e}", file=sys.stderr)
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    for attrs in ({"property": "og:description"}, {"name": "description"}):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            t = clean_lead(meta["content"])
            if len(t) >= 20:
                return t
    return ""


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
        with_lead = sum(1 for it in items if it["lead"])
        print(f"[info] page {page}: {len(items)}건 파싱 (리드문 {with_lead}건)")
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

    # 리드문 없는 기사 → 상세 페이지 폴백 (최신순, 실행당 상한)
    missing = [it for it in final if not it["lead"]]
    if missing:
        targets = missing[:DETAIL_FETCH_LIMIT]
        print(f"[info] 리드문 미확보 {len(missing)}건 중 {len(targets)}건 상세 조회")
        filled = 0
        for it in targets:
            lead = fetch_lead_from_detail(it["url"])
            if lead:
                it["lead"] = lead
                filled += 1
            time.sleep(DETAIL_FETCH_SLEEP)
        print(f"[info] 상세 조회로 리드문 {filled}건 보강")

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

    lead_total = sum(1 for it in final if it["lead"])
    print(f"[info] 저장 완료: 총 {len(final)}건 (기존 {prev_count} → 신규 +{new_count}, 리드문 보유 {lead_total}건)")
    if len(final) == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
