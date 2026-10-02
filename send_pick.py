"""
EDCF×AI 픽 메일 발송
- picks/*.html 파일을 Gmail SMTP로 발송 (링크 변환 없음)
- 제목: HTML의 <title>
- 환경변수: GMAIL_USER, GMAIL_APP_PASSWORD, MAIL_TO
"""
import html
import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr


def html_to_text(src: str) -> str:
    s = re.sub(r"(?is)<(script|style|title).*?</\1>", "", src)
    s = re.sub(r'(?is)<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2 (\1)", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|li|h\d)>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def send(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        body_html = f.read()
    m = re.search(r"(?is)<title>(.*?)</title>", body_html)
    subject = html.unescape(m.group(1).strip()) if m else os.path.basename(path)

    user = os.environ["GMAIL_USER"]
    to = os.environ["MAIL_TO"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("EDCF×AI 픽", user))
    msg["To"] = to
    msg.attach(MIMEText(html_to_text(body_html), "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, os.environ["GMAIL_APP_PASSWORD"])
        s.sendmail(user, [to], msg.as_string())
    print(f"[sent] {path} -> {to} / {subject}")


if __name__ == "__main__":
    files = [p for p in sys.argv[1:] if p.strip()]
    if not files:
        print("[info] 발송할 픽 파일 없음")
    for p in files:
        send(p)
