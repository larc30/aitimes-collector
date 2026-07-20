# -*- coding: utf-8 -*-
"""
AI타임스 과거 기사 백필 + 리드문 리프레시 스크립트
- 모드 1 (기본): idxno 역순 순회로 과거 기사 백필
- 모드 2 (REFRESH_LEADS=1): 이미 수집된 기사 중 리드문이 없거나
  중간에 잘린 것만 재방문해서 본문 첫 1~2문장으로 교체

사용 예:
  python backfill.py                      # 과거 기사 백필
  REFRESH_LEADS=1 python backfill.py      # 잘린 리드문 일괄 교체
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
ARTICLE_URL = BASE + "/news/articleView.html?idxno={idxno}"
UNTIL_DATE = os.environ.get("UNTIL_DATE", "2026-07-13")
START_IDXNO = os.environ.get("START_IDXNO", "")
REFRESH_LEADS = os.environ.get("REFRESH_LEADS", "") in ("1", "true", "yes")
MAX_STEPS = int(os.environ.get("MAX_STEPS", "300"))
STOP_STREAK = 8
MISS_STREAK_LIMIT = 30
SLEEP = 1.0
LEAD_MAX_LEN = 220
KEEP_DAYS = 15
KST = timezone(timedelta(hours=9))
IDX_RE = re.compile(r"idxno=(\d+)")
SENTENCE_END_RE = re.compile(r"[.!?」』\"']$")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Cache-Control": "no-cache",
}


# ---------- 리드문 공통 처리 (collect.py와 동일 로직) ----------

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
    cut = lead[:LEAD_MAX_LEN]
    ends = list(re.finditer(r"다\.|[.!?](?=\s|$)", cut))
    if ends:
        return cut[: ends[-1].end()]
    return cut.rstrip() + "…"


def lead_from_detail_soup(soup):
    lead = lead_from_body(soup)
    if len(lead) >= 30:
        return lead
    return cap_lead(
        meta_of(soup, property="og:description") or meta_of(soup, name="description")
    )


# ---------- 상세 페이지 파싱 ----------

def get_soup(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return None
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"[warn] fetch 실패 {url}: {e}", file=sys.stderr)
        return None


def fetch_article(idxno):
    """상세 페이지에서 기사 정보 추출. 기사가 아니거나 실패 시 None."""
    url = ARTICLE_URL.format(idxno=idxno)
    soup = get_soup(url)
    if soup is None:
        return None

    # 요청 idxno와 실제 응답 기사 일치 확인 (리다이렉트 방어)
    canon = meta_of(soup, property="og:url") or ""
    m = IDX_RE.search(canon)
    if m and m.group(1) != str(idxno):
        print(f"[warn] idxno={idxno} → {m.group(1)}로 리다이렉트됨, 건너뜀", file=sys.stderr)
        return None

    pub = meta_of(soup, property="article:published_time")
    if not pub:
        return None
    try:
        dt = datetime.fromisoformat(pub).astimezone(KST)
    except ValueError:
        return None

    title = meta_of(soup, property="og:title")
    title = re.sub(r"\s*-\s*AI타임스\s*$", "", title).strip()
    if not title:
        return None

    section = meta_of(soup, property="article:section1") or meta_of(soup, property="article:section")

    return {
        "title": title,
        "url": url,
        "date": dt.strftime("%Y-%m-%d %H:%M"),
        "section": section,
        "lead": lead_from_detail_soup(soup),
        "_dt": dt,
    }


# ---------- 저장 ----------

def load_json():
    if not os.path.exists("articles.json"):
        print("[error] articles.json 없음. collect.py 먼저 실행 필요.", file=sys.stderr)
        sys.exit(1)
    with open("articles.json", encoding="utf-8") as f:
        data = json.load(f)
    return {it["url"]: it for it in data.get("items", [])}


def min_idxno(merged):
    nums = [int(m.group(1)) for url in merged if (m := IDX_RE.search(url))]
    return min(nums) if nums else None


def write_outputs(merged, now, label):
    cutoff = now - timedelta(days=KEEP_DAYS)

    def in_range(it):
        if not it.get("date"):
            return True
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
        f"- 수집 시각: {now.strftime('%Y-%m-%d %H:%M')} KST / 총 {len(final)}건 ({label})",
        "",
    ]
    for it in final:
        sec = f"[{it['section']}] " if it.get("section") else ""
        lines.append(f"- {it['date']} | {sec}{it['title']}")
        lines.append(f"  {it['url']}")
        if it.get("lead"):
            lines.append(f"  · {it['lead']}")
    with open("articles.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return len(final)


# ---------- 모드별 실행 ----------

def run_backfill(merged, now):
    until = datetime.strptime(UNTIL_DATE, "%Y-%m-%d").replace(tzinfo=KST)
    if START_IDXNO:
        idxno = int(START_IDXNO)
    else:
        lo = min_idxno(merged)
        if lo is None:
            print("[error] 기존 데이터에서 idxno를 찾을 수 없음", file=sys.stderr)
            sys.exit(1)
        idxno = lo - 1

    print(f"[info] 백필 시작: idxno={idxno}부터 역순, {UNTIL_DATE}까지")
    added = 0
    old_streak = 0
    miss_streak = 0

    for _ in range(MAX_STEPS):
        item = fetch_article(idxno)
        if item is None:
            miss_streak += 1
            if miss_streak >= MISS_STREAK_LIMIT:
                print(f"[info] 연속 실패 {MISS_STREAK_LIMIT}건 → 종료")
                break
        else:
            miss_streak = 0
            dt = item.pop("_dt")
            if dt < until:
                old_streak += 1
                if old_streak >= STOP_STREAK:
                    print(f"[info] 목표일 이전 기사 연속 {STOP_STREAK}건 → 백필 완료")
                    break
            else:
                old_streak = 0
                if item["url"] not in merged:
                    merged[item["url"]] = item
                    added += 1
                    print(f"[info] +{item['date']} | {item['title'][:40]}")
        idxno -= 1
        time.sleep(SLEEP)
    return added, "백필 실행"


def run_refresh(merged, now):
    targets = [it for it in merged.values()
               if lead_is_truncated(it.get("lead", ""))][:MAX_STEPS]
    print(f"[info] 리드문 리프레시: 대상 {len(targets)}건")
    fixed = 0
    for it in targets:
        soup = get_soup(it["url"])
        if soup is None:
            time.sleep(SLEEP)
            continue
        lead = lead_from_detail_soup(soup)
        if lead and (not lead_is_truncated(lead) or not it.get("lead")):
            it["lead"] = lead
            fixed += 1
            print(f"[info] 교체 {it['date']} | {it['title'][:30]}")
        time.sleep(SLEEP)
    return fixed, "리드문 리프레시"


def main():
    now = datetime.now(KST)
    merged = load_json()
    prev = len(merged)

    if REFRESH_LEADS:
        changed, label = run_refresh(merged, now)
    else:
        changed, label = run_backfill(merged, now)

    total = write_outputs(merged, now, label)
    print(f"[info] 종료: 변경 {changed}건 (기존 {prev} → 최종 {total}건)")


if __name__ == "__main__":
    main()
