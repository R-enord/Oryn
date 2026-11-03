from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import yaml

from radar.context import Context
from radar.core.config import Config
from radar.core.db import Database
from radar.core.llm import LLM
from radar.core.notify import Notifier

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[1]

ENV_VARS = ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_OWNER_ID", "EMAIL_USER",
            "EMAIL_APP_PASSWORD", "EMAIL_TO", "SMTP_HOST", "SMTP_PORT", "RADAR_HOME"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


SOURCES = [
    {"name": "Blender Artists · Paid Work", "type": "rss", "url": "https://ba.test/paid.rss"},
    {"name": "WWR · Design", "type": "rss", "url": "https://wwr.test/design.rss"},
    {"name": "Jobicy · Design", "type": "jobicy", "url": "https://jobicy.test/api"},
    {"name": "Remote OK", "type": "remoteok", "url": "https://remoteok.test/api",
     "keywords": ["video editor", "blender", "3d"]},
]


def write_root(tmp_path: Path, *, settings: dict | None = None, sources: list | None = None,
               service: dict | None = None, env: str | None = None) -> Path:
    cfg = {
        "settings": {"max_age_days": 0, "exclude": [r"\[for hire\]"], **(settings or {})},
        "sources": SOURCES if sources is None else sources,
        "service": {"db_path": "data/radar.db", **(service or {})},
    }
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    (tmp_path / "profile.yaml").write_text("name: Salam\ncore_skills: [Blender product visualisation]\n",
                                           encoding="utf-8")
    if env is not None:
        (tmp_path / ".env").write_text(env, encoding="utf-8")
    return tmp_path


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(root=write_root(tmp_path))


@pytest.fixture
def db(tmp_path):
    database = Database.open(tmp_path / "data" / "radar.db")
    yield database
    database.close()


# ---------- fake Claude ----------

class Block(SimpleNamespace):
    def model_dump(self, **_: Any) -> dict:
        return {k: v for k, v in vars(self).items() if v is not None}


def tool_use(results: list[dict], name: str = "save_scores") -> Block:
    return Block(type="tool_use", id="toolu_1", name=name, input={"results": results})


def text(value: str) -> Block:
    return Block(type="text", text=value)


def search_result(*urls: str) -> Block:
    return Block(type="web_search_tool_result", tool_use_id="srvtoolu_1",
                 content=[SimpleNamespace(type="web_search_result", url=u, title="t") for u in urls])


def response(*blocks: Block, stop_reason: str = "end_turn", searches: int = 0) -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0,
                            cache_creation_input_tokens=0,
                            server_tool_use=SimpleNamespace(web_search_requests=searches))
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, usage=usage)


class FakeClaude:
    """Stands in for AsyncAnthropic. `script` is a list of responses, exceptions or callables(params)."""

    def __init__(self, script: list | None = None):
        self.script = list(script or [])
        self.calls: list[dict] = []
        self.messages = self

    async def create(self, **params):
        self.calls.append(params)
        if not self.script:
            raise AssertionError("FakeClaude: no scripted response left")
        nxt = self.script.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt(params) if callable(nxt) else nxt


def echo_scores(score_for) -> Any:
    """A scripted scorer reply that scores every item id in the request with score_for(item_text)."""
    import re

    def reply(params):
        content = params["messages"][0]["content"]
        results = []
        for m in re.finditer(r'<item id="([^"]+)">(.*?)</item>', content, re.S):
            score, track, location = score_for(m.group(2))
            results.append({"id": m.group(1), "score": score, "track": track, "location_ok": location,
                            "why": "test", "pay": "$500", "pitch": "lead with renders", "red_flags": ""})
        return response(tool_use(results), stop_reason="tool_use")

    return reply


# ---------- recording notifier ----------

class RecordingNotifier(Notifier):
    def __init__(self, *, telegram_ok: bool = True, email_ok: bool | None = True):
        super().__init__(bot=object(), chat_id=1, email_user="salam@example.com" if email_ok is not None else None,
                         email_password="pw" if email_ok is not None else None)
        self.telegram_ok = telegram_ok
        self.email_ok = email_ok
        self.sent: list[str] = []
        self.emails: list[tuple[str, str]] = []

    async def send(self, text: str, reply_markup=None) -> bool:
        self.sent.append(text)
        return self.telegram_ok

    async def email(self, subject: str, html_body: str, text_body: str) -> bool:
        self.emails.append((subject, text_body))
        return bool(self.email_ok)


def make_ctx(config: Config, db: Database, claude: FakeClaude | None = None,
             notifier: Notifier | None = None, fake_ai: bool = False) -> Context:
    return Context(config=config, db=db, http=httpx.AsyncClient(), llm=LLM(None, db, client=claude),
                   notifier=notifier or RecordingNotifier(), fake_ai=fake_ai)
