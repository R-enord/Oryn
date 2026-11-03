"""Daily open web research with Claude + web search, rotating focus by weekday (ported from v1)."""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

from radar.core.config import Settings
from radar.core.llm import LLM

log = logging.getLogger(__name__)

# Monday = 0 ... Sunday = 6. Edit these to steer the research.
FOCUS_BY_WEEKDAY = [
    ("Contests & prizes",
     "contests, challenges and competitions with cash prizes in 3D, CGI, product design, video or motion graphics that entrants in Nigeria can join"),
    ("Marketplace demand",
     "what is selling on 3D asset stores and Blender add-on marketplaces (Superhive/Blender Market, Fab, CGTrader, Gumroad) and specific gaps a solo artist could fill this month"),
    ("Brands needing visuals",
     "brands, startups and agencies currently looking for product visualisation, 3D product animation or CGI ads, especially furniture, footwear, consumer products and e-commerce"),
    ("AI training work",
     "paid, remote AI training, evaluation and data-creation work for 3D artists, video editors and programmers that is open to people in Nigeria"),
    ("Fresh freelance gigs",
     "fresh Blender, 3D and video-editing freelance gigs posted in the last few days on forums, Reddit, X and LinkedIn that accept worldwide applicants"),
    ("Stretch gigs",
     "small Go, Python or web-3D (three.js, product configurator) gigs, Blender add-on commissions and technical writing work open to worldwide freelancers"),
    ("Grants & business ideas",
     "grants, accelerators and programmes for creative entrepreneurs or agencies in Nigeria/Africa, plus original product-design ideas (footwear, furniture) with real demand"),
]

PROMPT = """Today is {date}. You are researching ways for Salam (profile below) to make money.

Today's focus: {focus}

Also find 1-3 fresh paid gigs posted in the last 3 days on Reddit hiring subs (r/forhire, r/HungryArtists, r/gameDevClassifieds), the Blender Artists "Paid Work" forum or Polycount that fit his core skills and accept worldwide applicants.

Rules:
- Use web search. Only include opportunities you actually found in search results, with their real URL.
- Skip anything that excludes applicants in Nigeria, is unpaid, looks like a scam, or that you cannot confirm is current.
- Do not repeat these already-reported links: {seen}
- Quality over quantity: 4-8 picks in total.

Finish with ONLY a JSON object inside <json></json> tags, in this shape:
<json>{"picks":[{"title":"...","url":"https://...","track":"core|stretch|business","what":"one sentence: what it is","why_you":"one sentence: why it fits Salam","first_step":"one concrete next action","deadline":"date or 'rolling'","potential":"rough USD or 'unknown'"}],"insight":"one sentence of market insight from today's research"}</json>

<profile>
{profile}
</profile>"""

MAX_CONTINUATIONS = 3  # long searches can pause; resume up to 3 times


def todays_focus(today: datetime) -> tuple[str, str]:
    return FOCUS_BY_WEEKDAY[today.weekday()]


def norm_url(url: str) -> str:
    return re.sub(r"[?#].*$", "", url or "").rstrip("/").lower()


def _block_to_param(block) -> dict:
    return block.model_dump(mode="json", exclude_none=True)


def build_prompt(profile_text: str, reported: list[str], today: datetime) -> str:
    _, focus = todays_focus(today)
    return (PROMPT.replace("{date}", today.strftime("%A %d %B %Y"))
            .replace("{focus}", focus)
            .replace("{seen}", ", ".join(reported[-60:]) or "none")
            .replace("{profile}", profile_text))


def parse_output(full_text: str, found_urls: set[str]) -> dict:
    matches = re.findall(r"<json>\s*(\{.*?\})\s*</json>", full_text, re.S)
    data: dict = {"picks": [], "insight": ""}
    if matches:
        try:
            data = json.loads(matches[-1], strict=False)
        except json.JSONDecodeError:
            data = {"picks": [], "insight": "", "error": "Could not read the research output."}
    else:
        data["error"] = "Research finished without a results block."
    picks = [p for p in data.get("picks", []) or [] if isinstance(p, dict)]
    for pick in picks:
        u = norm_url(pick.get("url", ""))
        pick["verified"] = bool(u) and any(f.startswith(u) or u.startswith(f) for f in found_urls)
    data["picks"] = picks
    return data


async def run_research(llm: LLM, profile_text: str, settings: Settings, reported: list[str],
                       today: datetime | None = None) -> dict:
    today = today or datetime.now(UTC)
    label, _ = todays_focus(today)
    tools = [{"type": settings.web_search_tool, "name": "web_search", "max_uses": int(settings.research_max_searches)}]
    user_msg = {"role": "user", "content": build_prompt(profile_text, reported, today)}
    assistant_blocks: list[dict] = []
    texts: list[str] = []
    found_urls: set[str] = set()
    refused = False

    for _ in range(MAX_CONTINUATIONS + 1):
        messages = [user_msg] + ([{"role": "assistant", "content": assistant_blocks}] if assistant_blocks else [])
        resp = await llm.create("research", model=settings.research_model, max_tokens=16000,
                                tools=tools, messages=messages)
        if resp.stop_reason == "refusal":
            refused = True
            break
        for block in resp.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "web_search_tool_result" and isinstance(block.content, list):
                for result in block.content:
                    url = getattr(result, "url", None)
                    if url:
                        found_urls.add(norm_url(url))
        if resp.stop_reason != "pause_turn":
            break
        assistant_blocks.extend(_block_to_param(b) for b in resp.content)

    data = parse_output("".join(texts), found_urls)
    if refused:
        data["error"] = "The model declined today's research request."
    data["focus"] = label
    return data


def fake_research(today: datetime | None = None) -> dict:
    label, _ = todays_focus(today or datetime.now(UTC))
    return {"focus": label, "insight": "Test run, no AI.", "picks": [{
        "title": "Example: furniture brand needs 3D renders", "url": "https://example.com/gig",
        "track": "core", "what": "Placeholder pick.", "why_you": "Furniture viz is your lane.",
        "first_step": "Send two furniture renders.", "deadline": "rolling", "potential": "$300-600",
        "verified": False}]}
