"""Scores new posts against your profile using a small, cheap Claude model."""
from __future__ import annotations

import re

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


def _format(items) -> str:
    blocks = []
    for it in items:
        meta = "; ".join(f"{k}: {v}" for k, v in it.meta.items() if v)
        parts = [f'<item id="{it.id}">', f"Source: {it.source}", f"Title: {it.title}"]
        if meta:
            parts.append(f"Details: {meta}")
        parts += [f"Text: {it.summary}", "</item>"]
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


def score_items(client, items, profile_text: str, settings: dict) -> tuple[dict, set]:
    """Returns ({item_id: result}, {ids from batches that completed})."""
    results, processed = {}, set()
    system = SYSTEM + "\n\n<profile>\n" + profile_text + "\n</profile>"
    size = max(1, int(settings["batch_size"]))
    for start in range(0, len(items), size):
        batch = items[start:start + size]
        try:
            resp = client.messages.create(
                model=settings["scorer_model"],
                max_tokens=4000,
                system=system,
                tools=[SCORE_TOOL],
                tool_choice={"type": "tool", "name": "save_scores"},
                messages=[{"role": "user", "content": "Score every listing below.\n\n" + _format(batch)}],
            )
        except Exception as exc:  # noqa: BLE001 — retry these items next run
            print(f"  scoring batch failed, will retry next run: {exc}")
            continue
        for block in resp.content:
            if block.type == "tool_use" and block.name == "save_scores":
                for r in block.input.get("results", []):
                    if r.get("id"):
                        results[r["id"]] = r
        processed.update(it.id for it in batch)
    return results, processed


def fake_score(items) -> tuple[dict, set]:
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
