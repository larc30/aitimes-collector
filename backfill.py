# -*- coding: utf-8 -*-
"""
AI타임스 과거 기사 백필 스크립트 (일회성)
- 목록 페이지네이션이 서버에서 막혀 있어(page=2+가 1페이지와 동일 응답)
  기사 idxno가 순차 발번인 점을 이용해 역순으로 상세 페이지를 직접 순회한다.
- 시작점: articles.json의 최소 idxno - 1 (또는 환경변수 START_IDXNO)
- 종료점: 게재일이 UNTIL_DATE(기본 2026-07-13) 이전인 기사가
  STOP_STREAK건 연속으로 나오면 중단
- 결과는 articles.json에 병합 후 articles.md 재생성 (collect.py와 동일 포맷)

사용 예:
  python backfill.py
  UNTIL_DATE=2026-07-13 START_IDXNO=212802 python backfill.py
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
UNTIL_DATE = os.environ.get("UNTIL_DATE", "2026-07-13")   # 이 날짜(포함)까지 수집
START_IDXNO = os.environ.get("START_IDXNO", "")           # 비우면 json 최소값-1
MAX_STEPS = int(os.environ.get("MAX_STEPS", "300"))       # 안전 상한
STOP_STREAK = 8          # 목표일 이전 기사 연속 N건이면 종료
MISS_STREAK_LIMIT = 30   # 404 등 연속 실패 N건이면 종료
SLEEP = 1.0
LEAD_MAX_LEN = 200
KEEP_DAYS = 15
KST = timezone(timedelta(hours=9))
IDX_RE = re.compile(r"idxno=(\d+)")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Cache-Control": "no-cache",
}


def clean_lead(text):
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip("…").rstrip("...")
    return text[:LEAD_MAX_LEN]


def meta(soup, **attrs):
    tag = soup.find("meta", attrs=attrs)
    return tag["content"].strip() if tag and tag.get("content") else ""


def fetch_article(idxno):
    """상세 페이지에서 기사 정보 추출. 기사가 아니거나 실패 시 None."""
    url = ARTICLE_URL.format(idxno=idxno)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return None
    except Exception as e:
        print(f"[warn] idxno={idxno} fetch 실패: {e}", file=sys.stderr)
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # 요청 idxno와 실제 응답 기사 일치 확인 (리다이렉트 방어)
    canon = meta(soup, property="og:url") or ""
    m = IDX_RE.search(canon)
    if m and m.group(1) != str(idxno):
        print(f"[warn] idxno={idxno} → {m.group(1)}로 리다이렉트됨, 건너뜀", file=sys.stderr)
        return None

    pub = meta(soup, property="article:published_time")  # 2026-07-15T16:36:00+09:00
    if not pub:
        return None  # 기사 아님 (삭제/공지 등)
    try:
        dt = datetime.fromisoformat(pub).astimezone(KST)
    except ValueError:
        return None

    title = meta(soup, property="og:title")
    title = re.sub(r"\s*-\s*AI타임스\s*$", "", title).strip()
    if not title:
        return None

    lead = clean_lead(meta(soup, property="og:description") or meta(soup, name="description"))
    section = meta(soup, property="article:section1") or meta(soup, property="article:section")

    return {
        "title": title,
        "url": url,
        "date": dt.strftime("%Y-%m-%d %H:%M"),
        "section": section,
        "lead": lead,
        "_dt": dt,
    }


def load_json():
    if not os.path.exists("articles.json"):
        print("[error] articles.json 없음. collect.py 먼저 실행 필요.", file=sys.stderr)
        sys.exit(1)
    with open("articles.json", encoding="utf-8") as f:
        data = json.load(f)
    return {it["url"]: it for it in data.get("items", [])}


def min_idxno(merged):
    nums = []
    for url in merged:
        m = IDX_RE.search(url)
        if m:
            nums.append(int(m.group(1)))
    return min(nums) if nums else None


def write_outputs(merged, now):
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
        f"- 수집 시각: {now.strftime('%Y-%m-%d %H:%M')} KST / 총 {len(final)}건 (백필 실행)",
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


def main():
    now = datetime.now(KST)
    until = datetime.strptime(UNTIL_DATE, "%Y-%m-%d").replace(tzinfo=KST)
    merged = load_json()
    prev = len(merged)

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

    for step in range(MAX_STEPS):
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
                print(f"[info] idxno={idxno} {item['date']} (목표일 이전, streak {old_streak})")
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

    total = write_outputs(merged, now)
    print(f"[info] 백필 종료: 신규 {added}건 추가 (기존 {prev} → 최종 {total}건)")


if __name__ == "__main__":
    main()
