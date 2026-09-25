"""Free AI providers for PrepWithTee, behind one OpenAI-compatible call.

Tutor's rule (2026-09-25): free tiers only. Each provider below turns on when
its key is in .env; model names change often on free tiers, so every one can
be overridden with EXPLAIN_<NAME>_MODEL. `python -m pipeline.explain --probe`
checks each configured provider with a tiny request.

    name        vision  free allowance (Sept 2026)              used by
    mistral     yes     ~1B tokens/month, ~1 req/s (Experiment)  drip + site  <- workhorse
    nvidia      no*     ~40 req/min (build.nvidia.com)           drip + site
    openrouter  no*     50 req/day (1000 after a $10 top-up)     drip
    groq_text   no      200k tokens/day (gpt-oss-120b)           drip (capped) - shared with live chat
    gemini      yes     small, often "over capacity"             drip + site
    groq        yes     200k tokens/day (qwen3.8 vision)         site only - the live Photo Solver's budget
    cloudflare  no      ~10k neurons/day (Workers AI)            drip
    ollama      no      unlimited, local (needs a GPU)           drip, off unless OLLAMA_URL is set
    (* the default model is text-only; a vision model can be set with EXPLAIN_<NAME>_MODEL
       plus EXPLAIN_<NAME>_VISION=1)
"""

import os
import re
import time

REQUEST_TIMEOUT = 120


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


def _flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None or v == "" else v.strip().lower() in ("1", "true", "yes", "on")


def registry() -> dict[str, dict]:
    """Provider settings, read from the environment each time (keys can be added live)."""
    cf_acct = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    return {
        "mistral": {
            "env": "MISTRAL_API_KEY", "url": "https://api.mistral.ai/v1/chat/completions",
            "model": _env("EXPLAIN_MISTRAL_MODEL", "mistral-medium-latest"),
            "vision": _flag("EXPLAIN_MISTRAL_VISION", True), "text": True,
            "min_gap": 1.3, "drip": True, "site": True, "max_tokens": 4000},
        "nvidia": {
            "env": "NVIDIA_API_KEY", "url": "https://integrate.api.nvidia.com/v1/chat/completions",
            "model": _env("EXPLAIN_NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"),
            "vision": _flag("EXPLAIN_NVIDIA_VISION", False), "text": True,
            "min_gap": 1.8, "drip": True, "site": True, "max_tokens": 4000},
        # OpenRouter's free models share ONE allowance per account (50 requests/day,
        # 1000 after a one-off $10 top-up), split here between a text and a vision model.
        "openrouter": {
            "env": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/chat/completions",
            "model": _env("EXPLAIN_OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"),
            "fallback": ["nvidia/nemotron-3-super-120b-a12b:free"],
            "vision": False, "text": True,
            "min_gap": 3.5, "per_day": int(_env("EXPLAIN_OPENROUTER_PER_DAY", "30")),
            "drip": True, "site": False, "max_tokens": 9000,     # it reasons first
            "headers": {"HTTP-Referer": "https://prepwithtee.com", "X-Title": "PrepWithTee"}},
        "openrouter_vision": {
            "env": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/chat/completions",
            "model": _env("EXPLAIN_OPENROUTER_VISION_MODEL", "qwen/qwen3.8-27b:free"),
            "fallback": ["google/gemma-4-31b-it:free"],
            "vision": True, "text": True,
            "min_gap": 3.5, "per_day": int(_env("EXPLAIN_OPENROUTER_VISION_PER_DAY", "15")),
            "drip": True, "site": False, "max_tokens": 4000,
            "headers": {"HTTP-Referer": "https://prepwithtee.com", "X-Title": "PrepWithTee"}},
        "groq_text": {
            "env": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/chat/completions",
            "model": _env("EXPLAIN_GROQ_TEXT_MODEL", "openai/gpt-oss-120b"),
            "vision": False, "text": True, "extra": {"reasoning_effort": "low"},
            "itpm": 8000, "per_day": int(_env("EXPLAIN_GROQ_TEXT_PER_DAY", "40")),
            "drip": True, "site": True, "max_tokens": 4000},
        "gemini": {
            "env": "GEMINI_API_KEY",
            "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            # 2.0/2.5-flash are retired; 3.x flash thinks first, so keep reasoning low.
            "model": _env("EXPLAIN_GEMINI_MODEL", "gemini-3.8-flash"), "fallback": ["gemini-3.5-flash"],
            "vision": True, "text": True, "extra": {"reasoning_effort": "low"},
            "min_gap": 4.0, "drip": True, "site": True, "max_tokens": 8000},
        "groq": {
            "env": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/chat/completions",
            "model": _env("EXPLAIN_GROQ_MODEL", "qwen/qwen3.8-27b"),
            "vision": True, "text": True, "extra": {"reasoning_effort": "none"}, "itpm": 7000,
            # Its 200k tokens/day is the live Photo Solver's: never in the background.
            "drip": _flag("EXPLAIN_GROQ_VISION_DRIP", False), "site": True, "max_tokens": 3500},
        "cloudflare": {
            "env": "CLOUDFLARE_API_TOKEN",
            "url": f"https://api.cloudflare.com/client/v4/accounts/{cf_acct}/ai/v1/chat/completions",
            "model": _env("EXPLAIN_CLOUDFLARE_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast"),
            "vision": False, "text": True, "min_gap": 3.0,
            "per_day": int(_env("EXPLAIN_CLOUDFLARE_PER_DAY", "25")),
            "drip": bool(cf_acct), "site": False, "max_tokens": 3500},
        "ollama": {
            "env": "OLLAMA_URL", "keyless": True,
            "url": _env("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/v1/chat/completions",
            "model": _env("EXPLAIN_OLLAMA_MODEL", "qwen2.5:7b-instruct"),
            "vision": False, "text": True, "drip": True, "site": False, "max_tokens": 3500},
    }


def configured(purpose: str | None = None) -> list[str]:
    """Providers with a key, in preference order; purpose 'drip' or 'site' filters."""
    reg = registry()
    out = []
    for name, p in reg.items():
        if not os.environ.get(p["env"]):
            continue
        if name == "cloudflare" and not os.environ.get("CLOUDFLARE_ACCOUNT_ID"):
            continue
        if purpose and not p.get(purpose):
            continue
        out.append(name)
    return out


class RateLimited(Exception):
    def __init__(self, wait: float, daily: bool, busy: bool = False):
        kind = "over capacity" if busy else "daily" if daily else "per-minute"
        super().__init__(f"rate limited ({kind}), wait {wait:.0f}s")
        self.wait, self.daily, self.busy = wait, daily, busy


def seconds(v: str | None) -> float:
    """Reset strings like '7.66s', '2m59.56s' or '1h2m3s' -> seconds."""
    if not v:
        return 0.0
    total, num = 0.0, ""
    for ch in v:
        if ch.isdigit() or ch == ".":
            num += ch
        else:
            total += float(num or 0) * {"h": 3600, "m": 60, "s": 1}.get(ch, 0)
            num = ""
    return total + (float(num) if num else 0.0)


def call(name: str, messages: list[dict], max_tokens: int | None = None, temperature: float = 0.2):
    """(text, usage, model, headers) from one provider. Raises RateLimited for
    429 / over-capacity (with how long to wait), RuntimeError otherwise."""
    import requests
    p = registry()[name]
    headers = {"Content-Type": "application/json", **p.get("headers", {})}
    if not p.get("keyless"):
        headers["Authorization"] = f"Bearer {os.environ[p['env']]}"
    last = None
    for model in [p["model"], *p.get("fallback", [])]:
        if last is not None and not getattr(last, "busy", False):
            break                                   # backups only help with "over capacity"
        try:
            r = requests.post(p["url"], timeout=REQUEST_TIMEOUT, headers=headers, json={
                "model": model, "messages": messages, "temperature": temperature,
                # No response_format: strict JSON mode rejects a whole answer over one
                # LaTeX backslash; the caller repairs and validates instead.
                "max_tokens": max_tokens or p.get("max_tokens", 3500), **p.get("extra", {})})
        except requests.RequestException as exc:
            last = RateLimited(30.0, False, busy=True)
            last.__cause__ = exc
            continue
        if r.status_code == 429:
            body = r.text.lower().replace(" ", "")
            daily = (r.headers.get("x-ratelimit-remaining-requests") == "0"
                     or "perday" in body or "tpd" in body or "rpd" in body or "daily" in body)
            said = re.search(r"try again in ([\d.hms]+)", r.text)
            wait = (float(r.headers.get("retry-after") or 0)
                    or (seconds(said.group(1)) if said else 0)
                    or seconds(r.headers.get("x-ratelimit-reset-requests" if daily
                                             else "x-ratelimit-reset-tokens")))
            last = RateLimited(max(wait, 2.0), daily)
            continue
        if r.status_code in (500, 502, 503, 504, 529):
            last = RateLimited(30.0, False, busy=True)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"{name} {r.status_code}: {r.text[:300]}")
        j = r.json()
        msg = (j.get("choices") or [{}])[0].get("message") or {}
        return msg.get("content") or "", j.get("usage") or {}, f"{name}:{model}", r.headers
    raise last


def probe() -> list[tuple[str, str]]:
    """[(provider, status)] - a 5-token request to every configured provider."""
    out = []
    for name in configured():
        p = registry()[name]
        t0 = time.time()
        try:
            text, _u, model, _h = call(name, [{"role": "user", "content": "Reply with the word OK."}],
                                       max_tokens=20)
            out.append((name, f"ok  {model}  {time.time() - t0:.1f}s  vision={p['vision']}  "
                              f"drip={bool(p.get('drip'))}  -> {text.strip()[:20]!r}"))
        except RateLimited as e:
            out.append((name, f"limited ({e})  {p['model']}"))
        except Exception as e:
            out.append((name, f"FAILED  {p['model']}  {str(e)[:160]}"))
    return out
