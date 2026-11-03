"""Outbound messages to Salam only: Telegram (his chat id) and the email digest (his inbox).

Nothing in here can address a third party: the Telegram chat id and the email recipient both come
from Salam's own .env, never from content or model output.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

from telegram import LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TelegramError

log = logging.getLogger(__name__)

TELEGRAM_LIMIT = 3900  # Telegram caps messages at 4096 characters
_TAG = re.compile(r"<[^>]+>")


def chunks(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Splits on blank lines so HTML tags stay intact (v1 behaviour)."""
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


def plain(text: str) -> str:
    return html.unescape(_TAG.sub("", text))


class Notifier:
    def __init__(self, bot: Any | None, chat_id: int | None, *, email_user: str | None = None,
                 email_password: str | None = None, email_to: str | None = None, smtp_host: str = "smtp.gmail.com",
                 smtp_port: int = 465, dry_run: bool = False):
        self.bot = bot
        self.chat_id = chat_id
        self.email_user = email_user
        self._email_password = email_password
        self.email_to = email_to or email_user
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.dry_run = dry_run

    @property
    def telegram_ready(self) -> bool:
        return bool(self.bot and self.chat_id)

    @property
    def email_ready(self) -> bool:
        return bool(self.email_user and self._email_password)

    async def send(self, text: str, reply_markup: Any = None) -> bool:
        """Sends to Salam's chat. Returns True if every chunk was delivered (or printed in dry-run)."""
        if self.dry_run or not self.telegram_ready:
            if not self.dry_run:
                log.warning("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID); printing instead")
            print("---- TELEGRAM ----\n" + text + "\n", flush=True)
            return self.dry_run
        parts = chunks(text)
        for i, chunk in enumerate(parts):
            markup = reply_markup if i == len(parts) - 1 else None
            if not await self._send_chunk(chunk, markup):
                return False
        return True

    async def _send_chunk(self, chunk: str, markup: Any) -> bool:
        kwargs = {"chat_id": self.chat_id, "reply_markup": markup,
                  "link_preview_options": LinkPreviewOptions(is_disabled=True)}
        for attempt in range(2):
            try:
                await self.bot.send_message(text=chunk, parse_mode=ParseMode.HTML, **kwargs)
                return True
            except RetryAfter as exc:
                if attempt:
                    break
                await asyncio.sleep(min(float(getattr(exc, "retry_after", 5) or 5), 60))
            except BadRequest as exc:
                if "parse" not in str(exc).lower():
                    log.warning("Telegram rejected a message: %s", exc)
                    return False
                # Broken HTML in content: resend as plain text rather than lose the message.
                try:
                    await self.bot.send_message(text=plain(chunk), **kwargs)
                    return True
                except TelegramError as exc2:
                    log.warning("Telegram plain-text resend failed: %s", exc2)
                    return False
            except TelegramError as exc:
                log.warning("Telegram send failed: %s", exc)
                return False
        return False

    async def email(self, subject: str, html_body: str, text_body: str) -> bool:
        if self.dry_run or not self.email_ready:
            if not self.dry_run:
                log.warning("Email not configured (EMAIL_USER / EMAIL_APP_PASSWORD); printing instead")
            print(f"---- EMAIL: {subject} ----\n{text_body}\n", flush=True)
            return self.dry_run
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.email_user
        msg["To"] = self.email_to
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")
        try:
            await asyncio.to_thread(self._smtp_send, msg)
        except Exception as exc:  # noqa: BLE001
            log.warning("Email failed: %s: %s", exc.__class__.__name__, str(exc)[:200])
            return False
        return True

    def _smtp_send(self, msg: EmailMessage) -> None:
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(self.email_user, self._email_password)
            smtp.send_message(msg)
