"""Formats Telegram alerts, the morning digest (Telegram + email) and /status. Ported from v1."""
from __future__ import annotations

from html import escape

TRACK = {"core": "Core", "stretch": "Stretch", "business": "Business"}
LOCATION = {"yes": "🌍 Open to you", "unclear": "🌍 Location unclear", "no": "⛔ Location restricted"}


def _e(value) -> str:
    return escape(str(value or ""))


def _real(value) -> bool:
    return bool(value) and str(value).strip().lower() not in {"none", "no", "n/a", "not stated", "-", "unknown"}


# ---------- Telegram ----------

def telegram_alert(r: dict) -> str:
    icon = "🔥" if r.get("score", 0) >= 85 else "✅"
    lines = [f'{icon} <b>{r.get("score")}</b> · {TRACK.get(r.get("track"), "")} · {_e(r.get("source"))}',
             f'<b>{_e(r.get("title"))}</b>']
    facts = []
    if _real(r.get("pay")):
        facts.append(f'💰 {_e(r["pay"])}')
    if r.get("location_ok") in LOCATION:
        facts.append(LOCATION[r["location_ok"]])
    if facts:
        lines.append(" · ".join(facts))
    if r.get("why"):
        lines.append(f'<i>Why:</i> {_e(r["why"])}')
    if r.get("pitch"):
        lines.append(f'<i>Pitch:</i> {_e(r["pitch"])}')
    if _real(r.get("red_flags")):
        lines.append(f'⚠️ {_e(r["red_flags"])}')
    lines.append(f'<a href="{_e(r.get("url"))}">Open post</a>')
    return "\n".join(lines)


def telegram_digest(date_label: str, matches: list[dict], research: dict, email_sent: bool | None = True) -> str:
    picks = research.get("picks", [])
    out = [f"☀️ <b>Money Radar · {_e(date_label)}</b>",
           f"{len(matches)} matches since yesterday · {len(picks)} research picks ({_e(research.get('focus'))})"]
    if matches:
        out.append("<b>Top matches</b>\n" + "\n".join(
            f'• {m.get("score")} · <a href="{_e(m.get("url"))}">{_e(m.get("title"))[:90]}</a>' for m in matches[:5]))
    if picks:
        out.append("<b>Research picks</b>\n" + "\n".join(
            f'• <a href="{_e(p.get("url"))}">{_e(p.get("title"))[:90]}</a> — {_e(p.get("first_step"))}' for p in picks[:5]))
    if research.get("error"):
        out.append(f"⚠️ Research step: {_e(research['error'])}")
    if email_sent:
        out.append("Full digest is in your inbox.")
    elif email_sent is False:
        out.append("⚠️ The email digest could not be sent; check the service log.")
    return "\n\n".join(out)


# ---------- Email ----------

def _badge(score: int) -> str:
    color = "#16a34a" if score >= 85 else "#2563eb" if score >= 70 else "#d97706"
    return (f'<span style="display:inline-block;min-width:34px;text-align:center;padding:3px 8px;'
            f'border-radius:999px;background:{color};color:#fff;font-weight:700;font-size:13px">{score}</span>')


def _chip(text: str) -> str:
    return (f'<span style="display:inline-block;padding:2px 8px;margin:0 4px 4px 0;border-radius:6px;'
            f'background:#eef2f7;color:#334155;font-size:12px">{_e(text)}</span>')


def _card(inner: str) -> str:
    return (f'<div style="border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;margin:0 0 12px;'
            f'background:#ffffff">{inner}</div>')


def _match_card(m: dict) -> str:
    chips = [TRACK.get(m.get("track"), ""), m.get("source", "")]
    if _real(m.get("pay")):
        chips.append(f'💰 {m["pay"]}')
    if m.get("location_ok") in LOCATION:
        chips.append(LOCATION[m["location_ok"]])
    body = [
        f'<div style="margin-bottom:6px">{_badge(int(m.get("score", 0)))} '
        f'<a href="{_e(m.get("url"))}" style="color:#0f172a;font-weight:700;font-size:15px;text-decoration:none">'
        f'{_e(m.get("title"))}</a></div>',
        "<div>" + "".join(_chip(c) for c in chips if c) + "</div>",
    ]
    if m.get("why"):
        body.append(f'<p style="margin:6px 0 0;color:#334155"><b>Why:</b> {_e(m["why"])}</p>')
    if m.get("pitch"):
        body.append(f'<p style="margin:4px 0 0;color:#334155"><b>Pitch:</b> {_e(m["pitch"])}</p>')
    if _real(m.get("red_flags")):
        body.append(f'<p style="margin:4px 0 0;color:#b45309">⚠️ {_e(m["red_flags"])}</p>')
    return _card("".join(body))


def _pick_card(p: dict) -> str:
    chips = [TRACK.get(p.get("track"), p.get("track", ""))]
    if _real(p.get("potential")):
        chips.append(f'💰 {p["potential"]}')
    if _real(p.get("deadline")):
        chips.append(f'⏳ {p["deadline"]}')
    if not p.get("verified"):
        chips.append("link not verified")
    body = [
        f'<a href="{_e(p.get("url"))}" style="color:#0f172a;font-weight:700;font-size:15px;text-decoration:none">'
        f'{_e(p.get("title"))}</a>',
        '<div style="margin-top:6px">' + "".join(_chip(c) for c in chips if c) + "</div>",
        f'<p style="margin:6px 0 0;color:#334155">{_e(p.get("what"))}</p>',
        f'<p style="margin:4px 0 0;color:#334155"><b>Why you:</b> {_e(p.get("why_you"))}</p>',
        f'<p style="margin:4px 0 0;color:#334155"><b>First step:</b> {_e(p.get("first_step"))}</p>',
    ]
    return _card("".join(body))


def _section(title: str, content: str) -> str:
    return (f'<h2 style="font-size:17px;margin:24px 0 10px;color:#0f172a">{_e(title)}</h2>{content}')


def digest_html(date_label: str, matches: list[dict], research: dict) -> str:
    picks = research.get("picks", [])
    parts = [
        '<div style="background:#f1f5f9;padding:20px 12px;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;'
        'font-size:14px;line-height:1.5">',
        '<div style="max-width:640px;margin:0 auto">',
        '<h1 style="font-size:22px;margin:0 0 4px;color:#0f172a">☀️ Money Radar</h1>',
        f'<p style="margin:0;color:#64748b">{_e(date_label)} · {len(matches)} matches · {len(picks)} research picks</p>',
    ]
    if research.get("insight"):
        parts.append(_card(f'<b>Today’s insight:</b> {_e(research["insight"])}'))
    if matches:
        parts.append(_section("Top matches since yesterday", "".join(_match_card(m) for m in matches[:25])))
    else:
        parts.append(_section("Top matches since yesterday", _card("Quiet day on the feeds. Nothing scored high enough.")))
    if picks:
        parts.append(_section(f"Research: {research.get('focus', '')}", "".join(_pick_card(p) for p in picks)))
    if research.get("error"):
        parts.append(_card(f'⚠️ Research step: {_e(research["error"])}'))
    parts.append('<p style="color:#94a3b8;font-size:12px;margin-top:20px">Tune scores, sources and your profile in '
                 'config.yaml and profile.yaml. Always check a client before sending work.</p></div></div>')
    return "".join(parts)


def digest_text(date_label: str, matches: list[dict], research: dict) -> str:
    lines = [f"MONEY RADAR · {date_label}", ""]
    if research.get("insight"):
        lines += [f"Insight: {research['insight']}", ""]
    lines.append("TOP MATCHES")
    for m in matches[:25]:
        lines += [f"[{m.get('score')}] {m.get('title')} ({m.get('source')})", f"  Why: {m.get('why', '')}",
                  f"  {m.get('url')}"]
    if not matches:
        lines.append("  none today")
    lines += ["", f"RESEARCH: {research.get('focus', '')}"]
    for p in research.get("picks", []):
        lines += [f"- {p.get('title')}", f"  {p.get('what', '')}", f"  First step: {p.get('first_step', '')}",
                  f"  {p.get('url')}"]
    if research.get("error"):
        lines.append(f"Research step: {research['error']}")
    return "\n".join(lines)
