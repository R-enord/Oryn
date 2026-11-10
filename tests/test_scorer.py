from radar.core.config import Settings
from radar.core.llm import LLM
from radar.opportunities import scorer
from radar.opportunities.sources.base import Item
from tests.conftest import FakeClaude, response, tool_use


def items(n: int) -> list[Item]:
    return [Item(id=f"id{i}", source="BA", title=f"Gig {i}", url=f"https://x.test/{i}", summary="Blender render",
                 published=None, meta={"jobGeo": "Anywhere"} if i == 0 else {}) for i in range(n)]


def result(i: int, **kw) -> dict:
    return {"id": f"id{i}", "score": 80, "track": "core", "location_ok": "yes", "why": "fits", **kw}


async def test_scores_are_parsed_and_batched(db):
    claude = FakeClaude([
        response(tool_use([result(0), result(1, score=40, track="skip")]), stop_reason="tool_use"),
        response(tool_use([result(2, score="91")]), stop_reason="tool_use"),
    ])
    llm = LLM(None, db, client=claude)
    scores, processed = await scorer.score_items(llm, items(3), "profile", Settings(batch_size=2))
    assert processed == {"id0", "id1", "id2"}
    assert scores["id0"]["score"] == 80 and scores["id1"]["track"] == "skip"
    assert scores["id2"]["score"] == 91  # numeric strings coerced
    first = claude.calls[0]
    assert first["model"] == "claude-haiku-5-5"
    assert first["tool_choice"] == {"type": "tool", "name": "save_scores"}
    assert "<profile>\nprofile\n</profile>" in first["system"]
    assert '<item id="id0">' in first["messages"][0]["content"] and "jobGeo: Anywhere" in first["messages"][0]["content"]
    assert db.usage_since("2000-01-01")["calls"] == 2  # every call is logged


async def test_failed_batch_is_retried_next_run(db):
    claude = FakeClaude([RuntimeError("overloaded"), response(tool_use([result(2)]))])
    llm = LLM(None, db, client=claude)
    scores, processed = await scorer.score_items(llm, items(3), "p", Settings(batch_size=2))
    assert processed == {"id2"}
    assert set(scores) == {"id2"}


async def test_results_for_unknown_ids_and_bad_values_are_ignored(db):
    claude = FakeClaude([response(tool_use([result(0, score="lots"), result(7), {"score": 50},
                                            result(1, track="weird", location_ok="maybe", score=150)]))])
    scores, processed = await scorer.score_items(LLM(None, db, client=claude), items(2), "p", Settings())
    assert processed == {"id0", "id1"}
    assert set(scores) == {"id1"}
    assert scores["id1"] == {**scores["id1"], "score": 100, "track": "skip", "location_ok": "unclear"}


async def test_refusal_marks_batch_seen_without_scores(db):
    claude = FakeClaude([response(stop_reason="refusal")])
    scores, processed = await scorer.score_items(LLM(None, db, client=claude), items(2), "p", Settings())
    assert scores == {} and processed == {"id0", "id1"}


async def test_missing_api_key_means_retry_later(db):
    scores, processed = await scorer.score_items(LLM(None, db), items(2), "p", Settings())
    assert scores == {} and processed == set()


def test_fake_score_needs_no_api():
    scores, processed = scorer.fake_score(items(1))
    assert processed == {"id0"} and scores["id0"]["score"] == 82
