from datetime import UTC, datetime

from radar.core.config import Settings
from radar.core.llm import LLM
from radar.opportunities import researcher
from tests.conftest import FakeClaude, response, search_result, text

MONDAY = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)

PICKS_JSON = """<json>{"picks":[
 {"title":"Render contest","url":"https://contest.example.com/2026?utm=x","track":"core","what":"w","why_you":"y",
  "first_step":"enter","deadline":"2026-12-01","potential":"$1000"},
 {"title":"Made up","url":"https://nowhere.example.com/x","track":"stretch","what":"w","why_you":"y",
  "first_step":"s","deadline":"rolling","potential":"unknown"}],
 "insight":"Contests are busy."}</json>"""


def test_focus_rotates_by_weekday():
    assert researcher.todays_focus(MONDAY)[0] == "Contests & prizes"
    assert researcher.todays_focus(datetime(2026, 11, 8, tzinfo=UTC))[0] == "Grants & business ideas"


def test_prompt_includes_profile_and_already_reported_links():
    prompt = researcher.build_prompt("PROFILE TEXT", ["https://a.example", "https://b.example"], MONDAY)
    assert "Monday 02 November 2026" in prompt
    assert "PROFILE TEXT" in prompt
    assert "https://a.example, https://b.example" in prompt
    assert "{" + "focus}" not in prompt


async def test_research_parses_json_and_verifies_links(db):
    claude = FakeClaude([response(search_result("https://contest.example.com/2026"), text("Found things.\n" + PICKS_JSON),
                                  searches=3)])
    data = await researcher.run_research(LLM(None, db, client=claude), "p", Settings(), [], MONDAY)
    assert data["focus"] == "Contests & prizes"
    assert data["insight"] == "Contests are busy."
    verified = {p["title"]: p["verified"] for p in data["picks"]}
    assert verified == {"Render contest": True, "Made up": False}
    call = claude.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["tools"] == [{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}]
    assert db.usage_since("2000-01-01")["searches"] == 3


async def test_pause_turn_is_resumed_with_previous_blocks(db):
    claude = FakeClaude([
        response(search_result("https://contest.example.com/2026"), text("Searching… "), stop_reason="pause_turn"),
        response(text(PICKS_JSON)),
    ])
    data = await researcher.run_research(LLM(None, db, client=claude), "p", Settings(), [], MONDAY)
    assert len(claude.calls) == 2
    resumed = claude.calls[1]["messages"]
    assert [m["role"] for m in resumed] == ["user", "assistant"]
    assert resumed[1]["content"][0]["type"] == "web_search_tool_result"
    assert len(data["picks"]) == 2 and data["picks"][0]["verified"]


async def test_missing_or_broken_json_is_reported():
    out = researcher.parse_output("no json here", set())
    assert out["picks"] == [] and "without a results block" in out["error"]
    out = researcher.parse_output("<json>{not json}</json>", set())
    assert "Could not read" in out["error"]


async def test_refusal_is_reported(db):
    claude = FakeClaude([response(stop_reason="refusal")])
    data = await researcher.run_research(LLM(None, db, client=claude), "p", Settings(), [], MONDAY)
    assert data["picks"] == [] and "declined" in data["error"]
