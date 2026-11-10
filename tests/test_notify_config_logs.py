import logging

import pytest
from telegram.error import BadRequest, NetworkError

from radar.core.config import Config, ServiceConfig
from radar.core.logs import RedactingFilter, setup_logging
from radar.core.notify import Notifier, chunks, plain
from radar.reports import render
from tests.conftest import REPO, write_root

# ---------- notifier ----------


def test_chunks_respect_limit_and_paragraphs():
    text = "\n\n".join(["a" * 1000] * 9)
    parts = chunks(text, limit=3900)
    assert all(len(p) <= 3900 for p in parts)
    assert "".join(parts).count("a") == 9000
    assert chunks("short") == ["short"]


class FakeBot:
    def __init__(self, errors=None):
        self.errors = list(errors or [])
        self.sent = []

    async def send_message(self, **kw):
        if self.errors:
            raise self.errors.pop(0)
        self.sent.append(kw)


async def test_send_goes_only_to_configured_chat():
    bot = FakeBot()
    n = Notifier(bot, 42)
    assert await n.send("<b>hi</b>")
    assert bot.sent[0]["chat_id"] == 42 and bot.sent[0]["parse_mode"] == "HTML"


async def test_broken_html_falls_back_to_plain_text():
    bot = FakeBot([BadRequest("Can't parse entities: unclosed tag")])
    n = Notifier(bot, 42)
    assert await n.send("<b>Pay &lt; $50 <i>oops")
    assert bot.sent[0]["text"] == "Pay < $50 oops" and "parse_mode" not in bot.sent[0]


async def test_network_failure_returns_false():
    n = Notifier(FakeBot([NetworkError("down")]), 42)
    assert await n.send("x") is False


async def test_dry_run_and_unconfigured_print(capsys):
    assert await Notifier(None, None, dry_run=True).send("hello") is True
    assert await Notifier(None, None).send("hello") is False
    assert await Notifier(None, None).email("s", "<p>h</p>", "t") is False
    assert "hello" in capsys.readouterr().out


def test_plain():
    assert plain('<a href="x">Open &amp; go</a>') == "Open & go"


def test_alert_render_escapes_post_content():
    msg = render.telegram_alert({"score": 90, "track": "core", "source": "BA", "title": "<script>x</script>",
                                 "url": "https://x/1", "why": "a & b", "pay": "$500", "location_ok": "yes",
                                 "red_flags": "none"})
    assert "&lt;script&gt;" in msg and "a &amp; b" in msg and "🔥" in msg and "⚠️" not in msg


# ---------- config ----------


def test_repo_config_and_profile_load():
    cfg = Config(root=REPO, env_file=None)
    assert cfg.settings.scorer_model == "claude-haiku-5-5"
    assert cfg.settings.web_search_tool == "web_search_20260209"
    assert len(cfg.app.enabled_sources) >= 6
    assert all(s.type in {"rss", "jobicy", "remoteok"} for s in cfg.app.sources)
    assert "Blender" in cfg.profile_text
    assert cfg.service.digest_time == "07:00" and cfg.service.timezone == "Africa/Lagos"


def test_secrets_from_env_file_and_owner_default(tmp_path):
    root = write_root(tmp_path, env="ANTHROPIC_API_KEY=sk-ant-test-123456\nTELEGRAM_BOT_TOKEN=1:abcdef\n"
                                     "TELEGRAM_CHAT_ID=4242\nTELEGRAM_OWNER_ID=\nEMAIL_USER=\n")
    cfg = Config(root=root)
    s = cfg.secrets
    assert s.telegram_chat_id == 4242 and s.owner_id == 4242 and s.telegram_ready
    assert s.email_user is None and not s.email_ready
    assert "sk-ant-test" not in repr(s) and "sk-ant-test" not in str(s.model_dump())
    assert "sk-ant-test-123456" in s.secret_values()


def test_env_vars_override_and_owner_can_differ(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "4242")
    monkeypatch.setenv("TELEGRAM_OWNER_ID", "777")
    cfg = Config(root=write_root(tmp_path))
    assert cfg.secrets.owner_id == 777
    assert not cfg.secrets.telegram_ready  # no token


def test_bad_times_are_rejected():
    with pytest.raises(ValueError):
        ServiceConfig(digest_time="7am")
    assert ServiceConfig(digest_time="06:30").digest_time == "06:30"


def test_reload_keeps_old_config_on_typo(tmp_path):
    root = write_root(tmp_path, settings={"alert_score": 70})
    cfg = Config(root=root)
    (root / "config.yaml").write_text("settings: {alert_score: 80}\nsources: []\n")
    assert cfg.reload() is None and cfg.settings.alert_score == 80
    (root / "config.yaml").write_text("settings: [this is: not valid\n")
    error = cfg.reload()
    assert error and "not reloaded" in error and cfg.settings.alert_score == 80
    (root / "config.yaml").write_text("settings: {alert_score: 85}\nservice: {watch_every_minutes: 10}\n")
    error = cfg.reload()
    assert error and "restart" in error
    assert cfg.settings.alert_score == 85 and cfg.service.watch_every_minutes == 30  # schedule unchanged until restart


# ---------- logs ----------


def test_redaction_masks_secrets_and_bot_urls(caplog):
    f = RedactingFilter(["sk-ant-supersecret"])
    assert f.redact("key=sk-ant-supersecret") == "key=***"
    assert f.redact("POST https://api.telegram.org/bot123:ABC-def/sendMessage") == \
        "POST https://api.telegram.org/bot***/sendMessage"


def test_redaction_applies_to_formatted_records(capsys):
    setup_logging(["sk-ant-supersecret"])
    logging.getLogger("test").warning("using %s at %s", "sk-ant-supersecret",
                                      "https://api.telegram.org/bot99:XYZ/getUpdates")
    out = capsys.readouterr().out
    assert "sk-ant-supersecret" not in out and "99:XYZ" not in out and "using *** at" in out
