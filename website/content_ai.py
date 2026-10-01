"""Writing help for the admin: blog posts, course pages, newsletters.

Free providers only (tutor, 2026-09-25), through pipeline/ai_providers.py in
the 'site' order (Mistral, NVIDIA, Groq text, Gemini...) - never the Groq
vision budget the live Photo Solver depends on. A provider that is rate
limited or down is skipped for the next one.

Every task asks for JSON that matches a small schema, validated here; one
retry with the validation error, then a clear error. Prompts are grounded in
real site facts (prices from billing.PERIODS, the subject list, features) and
real internal links (the site search index), and say "do not invent".

Prompt shape (every task):
    SYSTEM  voice + audience + subject + facts you may use + links you may use
            + "return ONLY JSON matching {schema}"
    USER    the admin's request + length / tone / keywords
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import ai_providers  # noqa: E402

SKIP = {"groq"}          # the live Photo Solver's vision budget


class AIUnavailable(Exception):
    """No configured provider could answer (none set up, all limited or failing)."""


# Shared with the live site's follow-up chat (capped per day): ask it last.
LAST = ("groq_text",)


def providers() -> list[str]:
    names = [n for n in ai_providers.configured("site") if n not in SKIP]
    names = names or [n for n in ai_providers.configured() if n not in SKIP]
    return [n for n in names if n not in LAST] + [n for n in names if n in LAST]


VOICE = ("You write for PrepWithTee (prepwithtee.com), an online Cambridge O Level, IGCSE and "
         "A Level study site and tutoring service run by Tee from Lahore, Pakistan. Voice: warm, "
         "direct, exam-focused, practical, British spelling, short paragraphs, no hype words "
         "(never 'unlock', 'seamless', 'elevate', 'game-changer'). Address students as 'you'.")


def site_facts() -> str:
    import billing
    import catalog
    subjects = "; ".join(f"{s['name']} {code} ({catalog.BOARD_SHORT[s['board_slug']]})"
                         for code, s in catalog.SUBJECTS.items())
    prices = "; ".join(
        f"{p['label']}: " + ", ".join(f"{billing.PLAN_LABELS[k]} PKR {v:,}" for k, v in p["amount"].items())
        for p in billing.PERIODS.values())
    return (f"Subjects: {subjects}. Plans: Free (limited), Solo (1 subject), 3 Subjects, All Subjects; "
            f"prices - {prices}. Features: topical past-paper booklets built from real Cambridge "
            f"questions with the official mark scheme, yearly past papers with mark schemes, timed MCQ "
            f"practice, mock tests, worked AI explanations and hints per question, an AI tutor, revision "
            f"notes, flashcards, progress tracking, 1-on-1 and small-group classes with Tee.")


def internal_links(subject: str | None = None, limit: int = 25) -> list[dict]:
    """Real pages to link to, from the site search index (subject pages first)."""
    try:
        import search
        rows = search.index_rows()
    except Exception:
        return []
    if subject:
        code = subject.strip()
        picked = [r for r in rows if code in (r.get("q") or "") or code in r.get("t", "")]
        rows = picked + [r for r in rows if r.get("k") == "page"]
    else:
        rows = [r for r in rows if r.get("k") in ("page", "subject")]
    seen, out = set(), []
    for r in rows:
        if r["u"] not in seen:
            seen.add(r["u"])
            out.append({"title": r["t"], "url": r["u"]})
        if len(out) >= limit:
            break
    return out


def _extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if m:
        text = m.group(1).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no JSON object in the reply")
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start:end + 1])


def _check(data, schema: dict) -> dict:
    """Light schema check: {field: (type, required)}; lists of str allowed."""
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    for field, (typ, required) in schema.items():
        if field not in data or data[field] in (None, ""):
            if required:
                raise ValueError(f"missing field '{field}'")
            continue
        v = data[field]
        if typ == "str" and not isinstance(v, str):
            raise ValueError(f"'{field}' must be a string")
        if typ == "list" and not isinstance(v, list):
            raise ValueError(f"'{field}' must be a list")
    return data


def generate(system: str, user: str, schema: dict, max_tokens: int = 3500,
             temperature: float = 0.6, call=None) -> tuple[dict, str]:
    """(validated JSON, 'provider:model'). Raises AIUnavailable."""
    call = call or ai_providers.call
    names = providers()
    if not names:
        raise AIUnavailable("No AI provider is configured on the server (add a MISTRAL_API_KEY, "
                            "NVIDIA_API_KEY or GEMINI_API_KEY to the environment).")
    fields = ", ".join(f'"{k}": {"[...]" if t == "list" else "..."}' for k, (t, _r) in schema.items())
    system = f"{system}\n\nReturn ONLY one JSON object, no prose before or after, with these keys: {{{fields}}}."
    errors = []
    for name in names:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for attempt in range(2):
            try:
                text, _usage, model, _h = call(name, msgs, max_tokens=max_tokens, temperature=temperature)
            except ai_providers.RateLimited as exc:
                if not exc.daily and not exc.busy and exc.wait <= 6 and attempt == 0:
                    import time
                    time.sleep(exc.wait + 0.5)          # a per-minute blip: wait it out once
                    try:
                        text, _usage, model, _h = call(name, msgs, max_tokens=max_tokens,
                                                       temperature=temperature)
                    except Exception as exc2:
                        errors.append(f"{name}: {exc2}")
                        break
                else:
                    errors.append(f"{name}: {exc}")
                    break                               # try the next provider
            except Exception as exc:
                errors.append(f"{name}: {str(exc)[:160]}")
                break
            try:
                out = _check(_extract_json(text), schema), model
                if errors:
                    print(f"[content_ai] answered by {model} after: {' | '.join(errors)}", flush=True)
                return out
            except (ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{name}: bad JSON ({exc})")
                msgs += [{"role": "assistant", "content": text[:4000]},
                         {"role": "user", "content": f"That was not valid: {exc}. Reply again with ONLY the JSON object."}]
    print(f"[content_ai] no usable answer: {' | '.join(errors)}", flush=True)
    raise AIUnavailable("The AI providers couldn't produce a usable answer just now. " + " | ".join(errors[-4:]))


def _context(audience: str | None, subject: str | None) -> str:
    links = internal_links(subject)
    link_lines = "\n".join(f"- {l['title']}: {l['url']}" for l in links)
    return (f"{VOICE}\nAudience: {audience or 'students'}.\n"
            + (f"Subject focus: {subject}.\n" if subject else "")
            + f"Facts you may use (do NOT invent other facts, prices, results or statistics):\n{site_facts()}\n"
            + (f"Internal pages you may link to (use ONLY these URLs, as markdown links):\n{link_lines}\n" if links else ""))


# ── blog ─────────────────────────────────────────────────────────────────────

OUTLINE = {"title": ("str", True), "angle": ("str", True), "sections": ("list", True)}
DRAFT = {"body_markdown": ("str", True), "excerpt": ("str", True), "slug": ("str", True),
         "meta_title": ("str", True), "meta_desc": ("str", True), "faq": ("list", False)}
EDIT = {"replacement": ("str", True)}
EDIT_ACTIONS = {
    "rewrite": "Rewrite it to read better, same meaning and length.",
    "simplify": "Rewrite it in simpler words a 15-year-old reads easily.",
    "expand": "Expand it with one or two more useful sentences, same style.",
    "shorten": "Make it about half as long, keeping the key point.",
    "add_example": "Add one short, concrete exam-style example after it.",
    "continue": "Write the next paragraph that should follow it.",
    "regenerate_section": "Rewrite this whole section (keep its heading) to be clearer and more useful.",
}


def blog_outline(prompt: str, audience: str | None, subject: str | None, tone: str | None,
                 length: int, keywords: str | None, call=None) -> tuple[dict, str]:
    system = _context(audience, subject) + ("\nPlan a blog post. 'sections' is a list of objects "
                                             "{\"h2\": heading, \"points\": [3-5 short bullet ideas]}; 4-7 sections.")
    user = (f"Post idea: {prompt}\nTarget length: about {length} words. Tone: {tone or 'friendly, exam-focused'}."
            + (f"\nKeywords to cover naturally: {keywords}." if keywords else ""))
    data, model = generate(system, user, OUTLINE, max_tokens=1500, call=call)
    data["sections"] = [s for s in data["sections"] if isinstance(s, dict) and s.get("h2")]
    if not data["sections"]:
        raise AIUnavailable("The outline came back without sections - try again.")
    return data, model


def blog_draft(outline: dict, audience: str | None, subject: str | None, tone: str | None,
               length: int, keywords: str | None, call=None) -> tuple[dict, str]:
    system = _context(audience, subject) + (
        "\nWrite the full blog post in Markdown from the outline: ## for the outline's headings, "
        "short paragraphs, bullet lists where useful, at least two internal links from the list, a "
        "closing call to action. Do not repeat the title as a heading. 'excerpt' is 1-2 sentences. "
        "'slug' is lowercase-with-hyphens. 'meta_title' at most 60 characters; 'meta_desc' 140-155 "
        "characters. 'faq' is a list of 2-4 {\"q\": ..., \"a\": ...} pairs.")
    user = (f"Outline JSON: {json.dumps(outline, ensure_ascii=False)}\n"
            f"Length: about {length} words. Tone: {tone or 'friendly, exam-focused'}."
            + (f"\nKeywords: {keywords}." if keywords else ""))
    data, model = generate(system, user, DRAFT, max_tokens=6000, call=call)
    data["slug"] = re.sub(r"[^a-z0-9]+", "-", data["slug"].lower()).strip("-")[:80] or "post"
    data["faq"] = [f for f in (data.get("faq") or []) if isinstance(f, dict) and f.get("q") and f.get("a")]
    return data, model


def blog_edit(action: str, selection: str, context: str, subject: str | None, call=None) -> tuple[dict, str]:
    if action not in EDIT_ACTIONS:
        raise ValueError(f"action must be one of {list(EDIT_ACTIONS)}")
    system = _context("students", subject) + ("\nYou edit one part of a blog post. Keep Markdown "
                                               "formatting. 'replacement' is ONLY the new text for the selected part.")
    user = (f"Instruction: {EDIT_ACTIONS[action]}\n\nSelected text:\n<<<\n{selection}\n>>>\n\n"
            f"Surrounding text, for context only:\n<<<\n{context[:3000]}\n>>>")
    return generate(system, user, EDIT, max_tokens=1500, temperature=0.5, call=call)


IDEA_TITLES = {"ideas": ("list", True)}


def polish_ideas(signals: list[dict], call=None) -> tuple[list[dict], str]:
    system = (VOICE + "\nTurn each signal from the site's own data into one blog post idea. 'ideas' is a "
              "list (same order) of {\"title\": ..., \"angle\": one sentence}.")
    user = json.dumps([{"signal": s["why"]} for s in signals], ensure_ascii=False)
    data, model = generate(system, user, IDEA_TITLES, max_tokens=1500, call=call)
    return data["ideas"], model


# ── course pages ─────────────────────────────────────────────────────────────

COURSE = {"tagline": ("str", True), "what_you_get": ("list", True), "overview_html": ("str", True),
          "approach_html": ("str", True), "faq": ("list", True), "meta_title": ("str", True),
          "meta_description": ("str", True)}
COURSE_FIELDS = tuple(COURSE)


def course_fields(code: str, level: str, title: str, notes: str | None, only: str | None = None,
                  call=None) -> tuple[dict, str]:
    import catalog
    chapters = [c["display"] for c in catalog.chapters(code)][:40] if code in catalog.SUBJECTS else []
    system = _context("parents and students choosing tuition", code) + (
        "\nWrite the landing page for one course. 'tagline' at most 90 characters. 'what_you_get' is "
        "exactly 5 short bullet strings. 'overview_html' and 'approach_html' are 2-3 <p> paragraphs "
        "each (only <p>, <strong>, <ul>, <li>, <a> tags). 'faq' is 4 {\"q\", \"a\"} pairs. 'meta_title' "
        "at most 60 characters; 'meta_description' 140-155 characters.")
    user = (f"Course: {title} ({level}, syllabus {code}).\n"
            + (f"Syllabus chapters (from the official syllabus): {'; '.join(chapters)}.\n" if chapters else "")
            + (f"Tutor's notes: {notes}\n" if notes else "")
            + (f"Only the '{only}' field matters this time; still return every key." if only else ""))
    data, model = generate(system, user, COURSE, max_tokens=3500, call=call)
    data["what_you_get"] = [str(x) for x in data["what_you_get"]][:6]
    data["faq"] = [f for f in data["faq"] if isinstance(f, dict) and f.get("q") and f.get("a")]
    for k in ("overview_html", "approach_html"):
        data[k] = clean_html(data[k])
    return data, model


_ALLOWED = {"p", "strong", "em", "ul", "ol", "li", "a", "br", "h3"}


def clean_html(html: str) -> str:
    """Keep a tiny tag set; drop attributes except a safe href."""
    def tag(m):
        closing, name, attrs = m.group(1), m.group(2).lower(), m.group(3) or ""
        if name not in _ALLOWED:
            return ""
        if name == "a" and not closing:
            href = re.search(r'href\s*=\s*"([^"]*)"', attrs)
            url = href.group(1) if href else ""
            if not url.startswith(("/", "https://")):
                return "<a>"
            return f'<a href="{url.replace(chr(34), "")}">'
        return f"<{closing}{name}>"
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    return re.sub(r"<(/?)([a-zA-Z0-9]+)([^>]*)>", tag, html)


# ── newsletter ───────────────────────────────────────────────────────────────

NEWS = {"subject": ("str", True), "body_markdown": ("str", True), "cta_label": ("str", False),
        "cta_url": ("str", False)}


def newsletter(prompt: str, recent_posts: list[dict], call=None) -> tuple[dict, str]:
    posts = "\n".join(f"- {p['title']}: /blog/{p['slug']} - {p.get('excerpt') or ''}" for p in recent_posts[:5])
    system = _context("students and parents on the mailing list", None) + (
        "\nWrite a short newsletter email in Markdown (150-250 words, a greeting, 2-4 short sections or "
        "bullets, signed 'Tee'). 'subject' under 60 characters. 'cta_label'/'cta_url' is one button "
        "(a URL from the lists or https://prepwithtee.com/...).")
    user = (f"What this issue is about: {prompt or 'the latest posts and what to practise this week'}\n"
            + (f"Recent blog posts you can feature:\n{posts}" if posts else ""))
    data, model = generate(system, user, NEWS, max_tokens=2000, call=call)
    url = (data.get("cta_url") or "").strip()
    if url and not url.startswith(("https://", "/")):
        data["cta_url"] = ""
    return data, model


def status() -> dict:
    """Which providers the writing tools would use (for the admin UI)."""
    return {"providers": providers(), "configured": bool(providers())}
