# -*- coding: utf-8 -*-
"""
AI타임스 기사목록 수집기 v3.1 (EDCF 주간픽용)
- 매일 실행: 목록 페이지를 긁어 기존 articles.json에 '누적 병합'
- 최근 KEEP_DAYS일치만 유지
- v3.1 변경점:
  * 리드문 문장 경계 트리밍: 중간에 잘린 꼬리 제거, 완결 문장으로 종료
  * 상세 페이지 폴백 시 meta 대신 기사 본문 첫 1~2문장 우선 추출
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
# 환경변수로 오버라이드 가능
MAX_PAGES = int(os.environ.get("MAX_PAGES", "3"))
KEEP_DAYS = 15           # 유지 기간 (주간픽 7일 + 여유)
DETAIL_FETCH_LIMIT = int(os.environ.get("DETAIL_FETCH_LIMIT", "15"))
DETAIL_FETCH_SLEEP = 1.0
LEAD_MAX_LEN = 220
KST = timezone(timedelta(hours=9))
DATE_RE = re.compile(r"(\d{2})-(\d{2})\s+(\d{2}):(\d{2})")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Cache-Control": "no-cache",
}

SENTENCE_END_RE = re.compile(r"[.!?」』\"']$")


# ---------- 리드문 공통 처리 ----------

def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def cap_lead(text, max_len=LEAD_MAX_LEN):
    """리드문 정리: 내용 최대 보존, 길이 초과 시에만 자르고 '…' 표시."""
    text = clean_text(text)
    if len(text) > max_len:
        return text[:max_len].rstrip() + "…"
    return text


def lead_is_truncated(lead):
    """리드문이 중간에 잘린 것으로 보이는지 판정."""
    if not lead:
        return True
    return not SENTENCE_END_RE.search(lead.strip())


def meta_of(soup, **attrs):
    tag = soup.find("meta", attrs=attrs)
    return tag["content"].strip() if tag and tag.get("content") else ""


def lead_from_body(soup):
    """기사 본문에서 첫 1~2문장 추출 (meta는 CMS가 잘라서 생성하므로 본문 우선).
    본문은 전체 원문이 있으므로 길이 내 완결 문장으로 구성 → 재방문 루프 방지."""
    body = soup.select_one(
        "#article-view-content-div, article#article-view-content-div, "
        ".article-body, #articleBody"
    )
    if not body:
        return ""
    parts = []
    total = 0
    for p in body.find_all("p"):
        t = clean_text(p.get_text(" ", strip=True))
        if len(t) < 30:
            continue
        if t.startswith("(사진") or t.startswith("사진=") or t.startswith("(출처"):
            continue
        if parts and total + len(t) + 1 > LEAD_MAX_LEN:
            break  # 다음 문단을 더하면 초과 → 여기까지 (완결 상태 유지)
        parts.append(t)
        total += len(t) + 1
        if len(parts) >= 2:
            break
    if not parts:
        return ""
    lead = " ".join(parts)
    if len(lead) <= LEAD_MAX_LEN:
        return lead
    # 첫 문단 하나가 이미 초과하는 드문 경우: 문장 경계에서 마무리
    cut = lead[:LEAD_MAX_LEN]
    ends = list(re.finditer(r"다\.|[.!?](?=\s|$)", cut))
    if ends:
        return cut[: ends[-1].end()]
    return cut.rstrip() + "…"


def lead_from_detail_soup(soup):
    """상세 페이지에서 리드문: 본문 우선, meta 폴백."""
    lead = lead_from_body(soup)
    if len(lead) >= 30:
        return lead
    return cap_lead(
        meta_of(soup, property="og:description") or meta_of(soup, name="description")
    )


# ---------- 수집 로직 ----------

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


def extract_lead_from_li(li, title):
    """목록 페이지 li 안에서 리드문 추출. 다중 셀렉터 → 폴백 순."""
    for sel in ("p.lead a", "p.lead", ".lead", "p.sbody", ".article-summary", "p.summary"):
        el = li.select_one(sel)
        if el:
            t = cap_lead(el.get_text(" ", strip=True))
            if len(t) >= 20:
                return t
    best = ""
    for p in li.find_all("p"):
        t = cap_lead(p.get_text(" ", strip=True))
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

        section = ""
        for em in li.select("em, span"):
            t = em.get_text(strip=True)
            if not t or DATE_RE.search(t) or t.endswith("기자") or len(t) > 20:
                continue
            section = t
            break

        items.append({
            "title": title,
            "url": url,
            "date": dt.strftime("%Y-%m-%d %H:%M") if dt else "",
            "section": section,
            "lead": extract_lead_from_li(li, title),
        })
    return items


def fetch_lead_from_detail(url):
    """상세 페이지 방문해서 리드문 추출 (본문 우선)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"[warn] 상세 fetch 실패 {url}: {e}", file=sys.stderr)
        return ""
    return lead_from_detail_soup(BeautifulSoup(r.text, "html.parser"))


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
            old = merged.get(it["url"], {})
            # 기존 리드가 완결 문장이면 유지, 아니면 새 것으로 교체 시도
            old_lead = old.get("lead", "")
            lead = old_lead if (old_lead and not lead_is_truncated(old_lead)) \
                else (it["lead"] or old_lead)
            merged[it["url"]] = {
                "title": it["title"] or old.get("title", ""),
                "url": it["url"],
                "date": it["date"] or old.get("date", ""),
                "section": it["section"] or old.get("section", ""),
                "lead": lead,
            }

    def in_range(it):
        if not it["date"]:
            return True
        dt = datetime.strptime(it["date"], "%Y-%m-%d %H:%M").replace(tzinfo=KST)
        return dt >= cutoff

    final = sorted(
        [it for it in merged.values() if in_range(it)],
        key=lambda x: x["date"], reverse=True,
    )

    # 리드문 없거나 잘린 기사 → 상세 페이지에서 본문 기반 재추출 (실행당 상한)
    missing = [it for it in final if lead_is_truncated(it.get("lead", ""))]
    if missing:
        targets = missing[:DETAIL_FETCH_LIMIT]
        print(f"[info] 리드문 미비 {len(missing)}건 중 {len(targets)}건 상세 조회")
        filled = 0
        for it in targets:
            lead = fetch_lead_from_detail(it["url"])
            if lead and not lead_is_truncated(lead):
                it["lead"] = lead
                filled += 1
            elif lead and not it.get("lead"):
                it["lead"] = lead  # 잘렸더라도 없는 것보단 나음
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
