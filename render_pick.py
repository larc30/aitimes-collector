"""
EDCF×AI 픽 JSON → 메일용 HTML 렌더러
- 사용: python render_pick.py picks/2026-10-16.json  → picks/2026-10-16.html 생성
- 메일 클라이언트 호환을 위해 table 레이아웃 + 인라인 스타일만 사용

JSON 구조:
{
  "period": "2026.10.01~10.15",
  "title_suffix": "",                       # 선택. 예: "(테스트)"
  "highlights": [ {"no": 3, "why": "한 줄 이유"} ],   # 2~3건
  "sections": [
    {"title": "국내 AI 정책", "items": [
      {"no": 1, "title": "...", "url": "...", "date": "YYYY-MM-DD",
       "summary": "...", "insight": "..."}
    ]}
  ]
}
"""
import html
import json
import sys
from pathlib import Path

FONT = "'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',Arial,sans-serif"
NAVY = "#1F3A5F"
ACCENT = "#2F6FB2"
INK = "#1F2328"
MUTED = "#6B7280"
LINE = "#E5E7EB"
HL_BG = "#FFF8E6"
HL_LINE = "#F2C14E"
INS_BG = "#F4F7FB"
SECTION_NUM = ["①", "②", "③", "④", "⑤", "⑥"]


def e(s: str) -> str:
    return html.escape(s or "", quote=True)


def render(d: dict) -> str:
    period = d["period"]
    suffix = d.get("title_suffix", "").strip()
    subject = f"[EDCF×AI 픽] {period}" + (f" {suffix}" if suffix else "")
    hl_nos = {h["no"] for h in d.get("highlights", [])}
    items_by_no = {it["no"]: it for s in d["sections"] for it in s["items"]}

    # ── 하이라이트 박스
    hl_rows = ""
    for h in d.get("highlights", []):
        it = items_by_no.get(h["no"], {})
        hl_rows += f"""
        <tr><td style="padding:10px 0;border-top:1px solid #F5DFA6;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
            <td valign="top" width="34" style="font:700 13px {FONT};color:{NAVY};padding-top:1px;">#{h['no']}</td>
            <td style="font:400 14px/1.55 {FONT};color:{INK};">
              <a href="{e(it.get('url',''))}" style="color:{INK};text-decoration:none;font-weight:700;">{e(it.get('title',''))}</a><br>
              <span style="color:#7A5B00;font-size:13px;">→ {e(h['why'])}</span>
            </td>
          </tr></table>
        </td></tr>"""

    highlight_block = f"""
    <tr><td style="padding:24px 28px 8px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{HL_BG};border:1px solid {HL_LINE};border-radius:8px;">
        <tr><td style="padding:16px 18px 6px;">
          <div style="font:700 15px {FONT};color:{NAVY};">⭐ 이번 회차 TOP 3</div>
        </td></tr>
        <tr><td style="padding:4px 18px 10px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{hl_rows}
          </table>
        </td></tr>
      </table>
    </td></tr>""" if hl_rows else ""

    # ── 섹션·항목
    body = ""
    for si, sec in enumerate(d["sections"]):
        num = SECTION_NUM[si] if si < len(SECTION_NUM) else str(si + 1)
        body += f"""
    <tr><td style="padding:26px 28px 6px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
        <td style="font:700 16px {FONT};color:{NAVY};border-bottom:2px solid {NAVY};padding-bottom:6px;">{num} {e(sec['title'])}</td>
      </tr></table>
    </td></tr>"""
        for it in sec["items"]:
            star = it["no"] in hl_nos
            badge_bg = HL_LINE if star else ACCENT
            badge_txt = "#3D2E00" if star else "#FFFFFF"
            star_tag = (f'<span style="display:inline-block;background:{HL_BG};border:1px solid {HL_LINE};'
                        f'color:#7A5B00;font:700 11px {FONT};padding:1px 6px;border-radius:10px;margin-left:6px;'
                        f'vertical-align:1px;">TOP 3</span>') if star else ""
            body += f"""
    <tr><td style="padding:12px 28px 4px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
        <td valign="top" width="34">
          <div style="width:24px;height:24px;font:700 12px/24px {FONT};text-align:center;border-radius:12px;background:{badge_bg};color:{badge_txt};">{it['no']}</div>
        </td>
        <td valign="top">
          <div style="font:700 15px/1.45 {FONT};">
            <a href="{e(it['url'])}" style="color:{INK};text-decoration:none;">{e(it['title'])}</a>{star_tag}
          </div>
          <div style="font:400 12px {FONT};color:{MUTED};padding:3px 0 8px;">{e(it['date'])}</div>
          <div style="font:400 14px/1.65 {FONT};color:{INK};">{e(it['summary'])}</div>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:10px;"><tr>
            <td style="background:{INS_BG};border-left:3px solid {ACCENT};padding:10px 12px;font:400 13.5px/1.6 {FONT};color:{INK};">
              <b style="color:{ACCENT};">EDCF 시사점</b>&nbsp; {e(it['insight'])}
            </td>
          </tr></table>
        </td>
      </tr></table>
    </td></tr>
    <tr><td style="padding:10px 28px 0;"><div style="border-bottom:1px solid {LINE};"></div></td></tr>"""

    total = sum(len(s["items"]) for s in d["sections"])
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(subject)}</title></head>
<body style="margin:0;padding:0;background:#EEF1F5;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#EEF1F5;"><tr><td align="center" style="padding:24px 12px;">
  <table role="presentation" width="680" cellpadding="0" cellspacing="0" style="width:100%;max-width:680px;background:#FFFFFF;border-radius:10px;overflow:hidden;border:1px solid {LINE};">
    <tr><td style="background:{NAVY};padding:22px 28px;">
      <div style="font:700 21px/1.35 {FONT};color:#FFFFFF;">📌 EDCF×AI 픽</div>
      <div style="font:400 13px {FONT};color:#C9D6E8;padding-top:4px;">{e(period)} · {total}건</div>
    </td></tr>{highlight_block}{body}
    <tr><td style="padding:18px 28px 22px;font:400 11.5px/1.6 {FONT};color:{MUTED};">
      본 메일은 AI타임스 공개 기사를 EDCF 조달 실무 관점에서 요약한 참고자료입니다. 매월 1일·16일 발송.
    </td></tr>
  </table>
</td></tr></table>
</body></html>
"""


if __name__ == "__main__":
    src = Path(sys.argv[1])
    data = json.loads(src.read_text(encoding="utf-8"))
    out = src.with_suffix(".html")
    out.write_text(render(data), encoding="utf-8")
    print(f"[render] {src} -> {out}")
