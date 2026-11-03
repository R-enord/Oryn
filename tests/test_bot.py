"""The bot must answer Salam, in Salam's chat, and nobody else."""
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from telegram import CallbackQuery, Chat, Message, MessageEntity, Update, User
from telegram.ext import ApplicationHandlerStop, CommandHandler, TypeHandler

from radar.core.bot import OwnerGuard, build_application, is_authorized

OWNER, CHAT, STRANGER = 111, 111, 999
FAKE_TOKEN = "123456:TEST-token-not-real"


def update(user_id: int | None, chat_id: int | None, text: str = "/status", callback: bool = False) -> Update:
    user = User(id=user_id, first_name="x", is_bot=False) if user_id else None
    chat = Chat(id=chat_id, type="private") if chat_id else None
    msg = None
    if chat:
        msg = Message(message_id=1, date=datetime.now(UTC), chat=chat, from_user=user, text=text,
                      entities=[MessageEntity(type="bot_command", offset=0, length=len(text.split()[0]))])
        msg.set_bot(SimpleNamespace(username="radar_bot"))
    if callback:
        cq = CallbackQuery(id="1", from_user=user, chat_instance="ci", message=msg, data="x")
        return Update(update_id=1, callback_query=cq)
    return Update(update_id=1, message=msg)


@pytest.mark.parametrize(("user_id", "chat_id", "ok"), [
    (OWNER, CHAT, True),          # Salam in his own chat
    (STRANGER, STRANGER, False),  # someone who found the bot
    (STRANGER, CHAT, False),      # someone else posting into Salam's chat id (e.g. a group)
    (OWNER, 555, False),          # Salam, but in another chat (e.g. a group someone added the bot to)
    (None, CHAT, False),          # channel posts have no user
])
def test_is_authorized(user_id, chat_id, ok):
    assert is_authorized(update(user_id, chat_id), OWNER, CHAT) is ok


def test_callback_queries_are_checked_too():
    assert is_authorized(update(OWNER, CHAT, callback=True), OWNER, CHAT)
    assert not is_authorized(update(STRANGER, CHAT, callback=True), OWNER, CHAT)


def test_missing_ids_fail_closed():
    assert not is_authorized(update(OWNER, CHAT), None, CHAT)
    assert not is_authorized(update(OWNER, CHAT), OWNER, None)


async def test_guard_stops_strangers_before_any_handler():
    guard = OwnerGuard(OWNER, CHAT)
    await guard(update(OWNER, CHAT), None)  # passes through silently
    with pytest.raises(ApplicationHandlerStop):
        await guard(update(STRANGER, STRANGER), None)


def test_application_wiring_puts_guard_first_and_filters_every_command():
    async def noop(u, c):
        return None

    app = build_application(FAKE_TOKEN, OWNER, CHAT, {"status": noop, "help": noop})
    guard_group = app.handlers[-1]
    assert len(guard_group) == 1 and isinstance(guard_group[0], TypeHandler)
    commands = [h for h in app.handlers[0] if isinstance(h, CommandHandler)]
    assert {next(iter(h.commands)) for h in commands} == {"status", "help"}
    for handler in commands:
        cmd = "/" + next(iter(handler.commands))
        assert handler.check_update(update(OWNER, CHAT, text=cmd))
        assert not handler.check_update(update(STRANGER, STRANGER, text=cmd))
        assert not handler.check_update(update(OWNER, 555, text=cmd))


async def test_full_dispatch_ignores_strangers(monkeypatch):
    """Runs real updates through the Application's dispatcher (no network)."""
    import telegram

    async def offline(self):
        return None

    monkeypatch.setattr(telegram.Bot, "initialize", offline)
    monkeypatch.setattr(telegram.Bot, "shutdown", offline)
    calls = []

    async def status(u, c):
        calls.append(u.effective_user.id)

    app = build_application(FAKE_TOKEN, OWNER, CHAT, {"status": status})
    async with app:
        for uid, cid in [(STRANGER, STRANGER), (STRANGER, CHAT), (OWNER, 555), (OWNER, CHAT)]:
            await app.process_update(update(uid, cid, text="/status"))
    assert calls == [OWNER]
