"""Sends Telegram messages and the email digest."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

import requests


def _chunks(text: str, limit: int = 3900) -> list[str]:
    """Telegram caps messages at 4096 chars; split on blank lines so HTML tags stay intact."""
    out, current = [], ""
    for part in text.split("\n\n"):
        candidate = f"{current}\n\n{part}" if current else part
        if len(candidate) > limit and current:
            out.append(current)
            current = part[:limit]
        else:
            current = candidate[:limit]
    if current:
        out.append(current)
    return out


def telegram_send(text: str, token: str | None, chat_id: str | None, dry_run: bool = False) -> bool:
    if dry_run or not token or not chat_id:
        if not dry_run:
            print("! Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID). Printing instead.")
        print("---- TELEGRAM ----\n" + text + "\n")
        return dry_run
    for chunk in _chunks(text):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML",
                      "link_preview_options": {"is_disabled": True}},
                timeout=20,
            )
        except requests.RequestException as exc:
            print(f"! Telegram request failed: {exc}")
            return False
        if not resp.ok:
            print(f"! Telegram error {resp.status_code}: {resp.text[:200]}")
            return False
    return True


def email_send(subject: str, html_body: str, text_body: str, user: str | None, password: str | None,
               to: str | None = None, host: str = "smtp.gmail.com", port: int = 465,
               dry_run: bool = False) -> bool:
    if dry_run or not user or not password:
        if not dry_run:
            print("! Email not configured (EMAIL_USER / EMAIL_APP_PASSWORD). Printing instead.")
        print(f"---- EMAIL: {subject} ----\n{text_body}\n")
        return dry_run
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to or user
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    try:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        print(f"! Email failed: {exc}")
        return False
    return True
