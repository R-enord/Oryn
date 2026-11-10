"""Salam's Telegram bot. It answers exactly one person in exactly one chat; everyone else is ignored.

Anyone can find and message a public bot, so the allowlist runs before every other handler
(group -1) and again as a filter on each command.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

log = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def is_authorized(update: Update, owner_id: int | None, chat_id: int | None) -> bool:
    """True only for Salam's user id, in Salam's chat. Missing ids fail closed."""
    if not owner_id or not chat_id:
        return False
    user = update.effective_user
    chat = update.effective_chat
    return bool(user and chat and user.id == owner_id and chat.id == chat_id)


class OwnerGuard:
    def __init__(self, owner_id: int | None, chat_id: int | None):
        self.owner_id = owner_id
        self.chat_id = chat_id
        self._logged: set[tuple] = set()

    async def __call__(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if is_authorized(update, self.owner_id, self.chat_id):
            return
        user = update.effective_user
        chat = update.effective_chat
        key = (user.id if user else None, chat.id if chat else None)
        if key not in self._logged and len(self._logged) < 1000:
            self._logged.add(key)
            log.warning("ignored Telegram update from user_id=%s chat_id=%s (not on the allowlist)", *key)
        raise ApplicationHandlerStop


COMMAND_MENU = [
    ("status", "Is everything running? Last runs, sources, usage"),
    ("scan", "Check all sources for new gigs now"),
    ("today", "Send today's digest now (runs research)"),
    ("help", "What I can do"),
]


def build_application(token: str, owner_id: int, chat_id: int, commands: dict[str, Handler],
                      bot_data: dict | None = None) -> Application:
    app = ApplicationBuilder().token(token).job_queue(None).build()
    if bot_data:
        app.bot_data.update(bot_data)
    app.add_handler(TypeHandler(Update, OwnerGuard(owner_id, chat_id)), group=-1)
    only_owner = filters.User(user_id=owner_id) & filters.Chat(chat_id=chat_id)
    for name, fn in commands.items():
        app.add_handler(CommandHandler(name, fn, filters=only_owner))
    if "help" in commands:
        app.add_handler(MessageHandler(only_owner & filters.COMMAND, commands["help"]))
    app.add_error_handler(_on_error)
    return app


async def set_command_menu(app: Application, chat_id: int) -> None:
    """Shows the command menu in Salam's chat only."""
    try:
        await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMAND_MENU],
                                      scope=BotCommandScopeChat(chat_id=chat_id))
    except Exception as exc:  # noqa: BLE001 — cosmetic
        log.warning("could not set the command menu: %s", exc)


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Telegram handler error: %s", context.error, exc_info=context.error)
