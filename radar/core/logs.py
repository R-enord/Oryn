"""Logging set-up. Secrets are masked in every log line, including third-party libraries.

python-telegram-bot's HTTP client logs request URLs, and Telegram puts the bot token in the URL,
so the redaction filter is not optional.
"""
from __future__ import annotations

import logging
import re
import sys

_BOT_URL = re.compile(r"(api\.telegram\.org/(?:file/)?bot)[^/\s]+")


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str] | None = None):
        super().__init__()
        self.secrets = [s for s in (secrets or []) if s and len(s) >= 6]

    def redact(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "***")
        return _BOT_URL.sub(r"\1***", text)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — never lose a log line over formatting
            return True
        clean = self.redact(message)
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        if clean != message or record.args:
            record.msg, record.args = clean, None
        return True


def setup_logging(secrets: list[str] | None = None, level: int = logging.INFO) -> RedactingFilter:
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
    redactor = RedactingFilter(secrets)
    handler.addFilter(redactor)
    root.addHandler(handler)
    root.setLevel(level)
    # Chatty libraries: keep their warnings, drop per-request noise (which also carries URLs).
    for name in ("httpx", "httpcore", "httpx2", "telegram", "telegram.ext", "apscheduler", "anthropic"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return redactor
