"""Scores new posts against Salam's profile with a small, cheap Claude model (ported from v1).

Structured output comes from a forced tool call (`save_scores`). Claude Haiku 5.5 accepts a forced
tool_choice; if the scorer model is switched to one that doesn't (e.g. Sonnet 5.5), the call fails
loudly and the batch is retried next run rather than being silently dropped.
"""
from __future__ import annotations

import logging
import re

from radar.core.config import Settings
from radar.core.llm import LLM

from .sources.base import Item

log = logging.getLogger(__name__)

SCORE_TOOL = {
    "name": "save_scores",
    "description": "Save the score for every listing.",
    "input_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "score": {"type": "integer", "minimum": 0, "maximum": 100},
                        "track": {"type": "string", "enum": ["core", "stretch", "skip"]},
                        "pay": {"type": "string", "description": "Pay/budget as stated (rough USD if possible), or 'not stated'."},
                        "location_ok": {"type": "string", "enum": ["yes", "no", "unclear"]},
                        "why": {"type": "string", "description": "One sentence."},
                        "pitch": {"type": "string", "description": "One sentence: the angle to lead the application with."},
                        "red_flags": {"type": "string", "description": "Scam/exploitation signals, or empty."},
                    },
                    "required": ["id", "score", "track", "location_ok", "why"],
                },
            }
        },
        "required": ["results"],
    },
}

SYSTEM = """You are Salam's talent agent. You read freelance gigs and job posts and decide, honestly, which are worth his time. His profile is below.

Score each listing 0-100:
- 85-100: strong fit, he should apply today
- 70-84: good fit, worth a tailored pitch
- 50-69: possible: a stretch, low pay, or unclear details
- 0-49: skip

Rules:
- track "core" = uses his main skills. "stretch" = outside his core but realistic for him within a few weeks, given his background. "skip" = not for him.
- If the post requires living in, or being authorised to work in, a country or region that excludes Nigeria ("US only", "EU residents", "must be in London"), set location_ok "no" and score 30 or less. Worldwide/anywhere is "yes". Not stated is "unclear".
- Anything matching his avoid list scores 25 or less.
- Scam or exploitation signals (upfront fees, cheque or gift-card payments, a recruiter reachable only on Telegram/WhatsApp with no real company, a big unpaid "test" that is really the job, exposure or revenue-share only): describe them in red_flags and score 20 or less.
- Remote full-time roles count if they are open to him.
- why = one sentence. pitch = one sentence on the angle he should lead with (a matching project type, a quick sample, turnaround). Never invent facts about a post.
- Return a result for every item id."""


def format_items(items: list[Item]) -> str:
    blocks = []
    for it in items:
        meta = "; ".join(f"{k}: {v}" for k, v in it.meta.items() if v)
        parts = [f'<item id="{it.id}">', f"Source: {it.source}", f"Title: {it.title}"]
        if meta:
            parts.append(f"Details: {meta}")
        parts += [f"Text: {it.summary}", "</item>"]
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


def normalise(result: dict) -> dict | None:
    """Coerces one tool result into the stored shape; returns None if it is unusable."""
    if not isinstance(result, dict) or not result.get("id"):
        return None
    try:
        score = max(0, min(100, int(result.get("score", 0))))
    except (TypeError, ValueError):
        return None
    track = result.get("track") if result.get("track") in {"core", "stretch", "skip"} else "skip"
    location = result.get("location_ok") if result.get("location_ok") in {"yes", "no", "unclear"} else "unclear"
    return {
        "id": str(result["id"]), "score": score, "track": track, "location_ok": location,
        "pay": str(result.get("pay") or ""), "why": str(result.get("why") or ""),
        "pitch": str(result.get("pitch") or ""), "red_flags": str(result.get("red_flags") or ""),
    }


async def score_items(llm: LLM, items: list[Item], profile_text: str, settings: Settings) -> tuple[dict, set]:
    """Returns ({item_id: result}, {ids from batches that completed}).

    Items from a failed batch are left out of the second set, so the next run retries them.
    """
    results: dict[str, dict] = {}
    processed: set[str] = set()
    system = SYSTEM + "\n\n<profile>\n" + profile_text + "\n</profile>"
    size = max(1, int(settings.batch_size))
    for start in range(0, len(items), size):
        batch = items[start:start + size]
        batch_ids = {it.id for it in batch}
        try:
            resp = await llm.create(
                "score",
                model=settings.scorer_model,
                max_tokens=4000,
                system=system,
                tools=[SCORE_TOOL],
                tool_choice={"type": "tool", "name": "save_scores"},
                messages=[{"role": "user", "content": "Score every listing below.\n\n" + format_items(batch)}],
            )
        except Exception as exc:  # noqa: BLE001 — retry these items next run
            log.warning("scoring batch of %d failed, will retry next run: %s", len(batch), exc)
            continue
        if getattr(resp, "stop_reason", None) == "refusal":
            # Retrying the same posts would be refused again; mark them seen without a score.
            log.warning("scoring batch of %d was declined by the model; skipping these posts", len(batch))
            processed.update(batch_ids)
            continue
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "save_scores":
                for raw in (block.input or {}).get("results", []) or []:
                    r = normalise(raw)
                    if r and r["id"] in batch_ids:
                        results[r["id"]] = r
        processed.update(batch_ids)
    return results, processed


def fake_score(items: list[Item]) -> tuple[dict, set]:
    """Keyword-only scoring for testing without an API key (--fake-ai)."""
    results = {}
    for it in items:
        text = f"{it.title} {it.summary}".lower()
        if re.search(r"blender|3d|render|product visual", text):
            score, track = 82, "core"
        elif re.search(r"video|motion|design", text):
            score, track = 60, "stretch"
        else:
            score, track = 20, "skip"
        results[it.id] = {"id": it.id, "score": score, "track": track, "pay": "not stated",
                          "location_ok": "unclear", "why": "Test score (no AI).", "pitch": "", "red_flags": ""}
    return results, {it.id for it in items}
