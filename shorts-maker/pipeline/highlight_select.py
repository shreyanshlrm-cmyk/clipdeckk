"""
highlight_select.py
Decides which moments of the source video become individual shorts, and
packages each one for upload: an SEO-focused title + description, tags,
hashtags, and an estimated virality score with a one-line reason.

Two modes:
  1. AI mode: works with ANY of the three major providers - Anthropic,
     OpenAI, or Google Gemini. Pass an explicit provider, or just pass a key
     and the provider is guessed from its prefix, or leave the key blank and
     it's picked up from ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
     in the environment (this is how the GitHub Actions backend feeds it a
     key via repo secrets, without ever putting the key in a request body).
  2. Heuristic mode (always available, free, fully offline): scores windows
     of the transcript using punctuation, keyword cues and pacing, and picks
     the strongest non-overlapping windows. Still produces titles,
     descriptions, tags and an estimated virality score - just with simpler
     methods than a full LLM. Used automatically if no key is available
     anywhere, or if the API call fails for any reason.

Either way, every returned clip's start/end is snapped onto real whisper
segment boundaries so cuts never land mid-word, and clip length is clamped
to [min_len, max_len].
"""
import json
import os
import re

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
}

PROVIDER_ENV_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "so", "to", "of", "in", "on", "for",
    "is", "it", "this", "that", "was", "were", "with", "as", "at", "by", "be",
    "are", "i", "you", "we", "they", "he", "she", "them", "his", "her", "my",
    "me", "your", "our", "just", "like", "um", "uh", "yeah", "okay", "ok",
    "there", "here", "if", "then", "than", "have", "has", "had", "do", "does",
    "did", "not", "no", "yes", "all", "can", "will", "would", "could", "should",
}

HOOK_KEYWORDS = [
    "secret", "never", "always", "mistake", "wrong", "worst", "best", "crazy",
    "insane", "shocking", "nobody", "everyone", "truth", "reality", "actually",
    "important", "why", "how to", "biggest", "huge", "warning", "stop",
    "tip", "hack", "trick", "story", "honestly", "real talk", "let me tell you",
]


# ---------------------------------------------------------------- utilities

def _fmt_ts(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m:02d}:{s:05.2f}"


def _transcript_text(segments) -> str:
    lines = [f"[{_fmt_ts(s['start'])} - {_fmt_ts(s['end'])}] {s['text']}" for s in segments]
    return "\n".join(lines)


def _snap_to_segments(start, end, segments, min_len, max_len):
    """Pull start/end onto real segment boundaries so we never cut mid-sentence."""
    if not segments:
        return max(0.0, start), max(start + min_len, end)

    starts = [s["start"] for s in segments]
    ends = [s["end"] for s in segments]

    snapped_start = min(starts, key=lambda x: abs(x - start))
    candidates_end = [e for e in ends if e > snapped_start]
    snapped_end = min(candidates_end, key=lambda x: abs(x - end)) if candidates_end else max(ends)

    if snapped_end - snapped_start < min_len:
        for e in sorted(ends):
            if e - snapped_start >= min_len:
                snapped_end = e
                break
        else:
            snapped_end = max(ends)

    if snapped_end - snapped_start > max_len:
        capped = [e for e in ends if snapped_start < e <= snapped_start + max_len]
        snapped_end = max(capped) if capped else snapped_start + max_len

    return snapped_start, snapped_end


def _words_in_range(all_words, start, end):
    return [w for w in all_words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]


def _default_num_clips(duration):
    return max(3, min(10, round(duration / 90)))


def _clamp_int(value, lo, hi, default):
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def resolve_provider_and_key(provider, api_key):
    """
    Works out which AI provider to use and which key to use for it, so the
    caller can hand this "any key the user gave it" and have it just work:
      - provider == "none" -> force the offline heuristic, even if API keys
        are sitting in the environment (explicit opt-out always wins)
      - explicit provider + key -> use exactly that
      - key only, no provider (or provider="auto") -> guess from key prefix
      - no key at all -> look for ANTHROPIC_API_KEY / OPENAI_API_KEY /
        GEMINI_API_KEY in the environment (repo secrets land here in the
        GitHub Actions backend)
      - nothing found anywhere -> (None, None), caller should fall back to
        the offline heuristic picker
    """
    if provider == "none":
        return None, None

    if api_key and provider and provider != "auto":
        return provider, api_key

    if api_key:
        key = api_key.strip()
        if key.startswith("sk-ant-"):
            return "anthropic", key
        if key.startswith("AIza"):
            return "gemini", key
        if key.startswith("sk-"):
            return "openai", key
        return "anthropic", key  # reasonable default guess

    order = [provider] if provider and provider != "auto" else ["anthropic", "openai", "gemini"]
    for p in order:
        env_name = PROVIDER_ENV_KEYS.get(p)
        if env_name and os.environ.get(env_name):
            return p, os.environ[env_name]

    return None, None


# ------------------------------------------------------------- prompt + LLM

def _build_prompt(segments, duration, min_len, max_len, target_n):
    transcript = _transcript_text(segments)

    system = (
        "You are a short-form video producer AND an SEO strategist for YouTube "
        "Shorts, Instagram Reels and TikTok. You select the strongest "
        "stand-alone moments from a transcript and package each one to "
        "maximize both discoverability (search/recommendation) and "
        "watch-through/shares."
    )

    user = f"""Video duration: {duration:.1f}s

Transcript with timestamps (mm:ss.ms):
{transcript}

TASK
Pick up to {target_n} clips, each between {min_len:.0f} and {max_len:.0f}
seconds long, ranked best-first, non-overlapping. Each clip must work with
zero outside context, open on a hook within its first 2 seconds, and land on
a finished thought.

SEO REQUIREMENTS - this is the part that matters most, be genuinely good at it:
- "title": hook-first and keyword-rich. Put the single most-searched keyword
  or the sharpest hook within the first 40 characters (mobile UIs truncate
  past that). 40-70 characters total. No ALL CAPS, no misleading clickbait.
- "description": 2-4 sentences. Sentence 1 contains the primary keyword and
  restates the hook (platforms only show this much before "...more"). Then
  1-2 sentences of natural supporting/secondary keywords, then a short
  call-to-action. Put 3-6 hashtags at the very end, never inline.
- "tags": 8-15 plain keywords/short phrases (no # symbol) - the exact topic,
  the broader topic, and the format - phrased the way someone would actually
  search.
- "hashtags": 3-6 tags (with #), mixing one broad discovery tag (e.g.
  #shorts) with specific topical tags. No spaces inside a tag.
- "virality_score": your honest 0-100 estimate of this exact clip's
  share/watch-through potential in isolation.
- "virality_reason": one sentence on what drives that score (hook strength,
  emotional payoff, pacing, curiosity gap, relatability, etc).

Respond with ONLY raw JSON, no markdown fences, no commentary, in this exact
shape:
{{"clips": [{{"start": 12.3, "end": 45.6, "title": "...", "description": "...",
"tags": ["...", "..."], "hashtags": ["#tag1", "#tag2"], "virality_score": 82,
"virality_reason": "..."}}]}}
"""
    return system, user


def _call_anthropic(system, user, api_key, model):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model or DEFAULT_MODELS["anthropic"],
        max_tokens=3000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _call_openai(system, user, api_key, model):
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model or DEFAULT_MODELS["openai"],
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


def _call_gemini(system, user, api_key, model):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    gmodel = genai.GenerativeModel(model or DEFAULT_MODELS["gemini"], system_instruction=system)
    resp = gmodel.generate_content(
        user, generation_config={"response_mime_type": "application/json"}
    )
    return resp.text


_PROVIDER_CALLS = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "gemini": _call_gemini,
}


def select_highlights_ai(segments, duration, provider, api_key, min_len=15, max_len=90,
                          num_clips=None, model=None):
    """Ask the chosen AI provider to pick the best moments and write their
    SEO metadata. Raises on any failure so the caller can fall back to the
    heuristic picker."""
    if provider not in _PROVIDER_CALLS:
        raise ValueError(f"Unknown or unsupported AI provider: {provider}")

    target_n = num_clips or _default_num_clips(duration)
    system, user = _build_prompt(segments, duration, min_len, max_len, target_n)

    raw = _PROVIDER_CALLS[provider](system, user, api_key, model)
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    data = json.loads(text)
    raw_clips = data.get("clips", [])
    if not raw_clips:
        raise ValueError("Model returned no clips")

    all_words = [w for s in segments for w in s["words"]]
    results = []
    used_ranges = []
    for c in raw_clips:
        try:
            start, end = _snap_to_segments(float(c["start"]), float(c["end"]), segments, min_len, max_len)
        except (KeyError, ValueError, TypeError):
            continue
        if any(not (end <= u[0] or start >= u[1]) for u in used_ranges):
            continue  # overlaps a clip we already accepted
        used_ranges.append((start, end))
        results.append({
            "start": start,
            "end": end,
            "words": _words_in_range(all_words, start, end),
            "title": str(c.get("title", "Untitled clip"))[:100],
            "description": str(c.get("description", ""))[:500],
            "tags": [str(t)[:30] for t in list(c.get("tags", []))[:15]],
            "hashtags": [str(t)[:30] for t in list(c.get("hashtags", []))[:8]],
            "virality_score": _clamp_int(c.get("virality_score"), 0, 100, default=50),
            "virality_reason": str(c.get("virality_reason", ""))[:200],
        })

    if not results:
        raise ValueError("No valid clips after snapping/validation")
    return results


# --------------------------------------------------------- offline fallback

def _extract_tags(text, limit=12):
    raw_words = re.findall(r"[a-zA-Z']{2,}", text.lower())
    seen = []
    for w in raw_words:
        cleaned = re.sub(r"'s$", "", w).replace("'", "")
        if len(cleaned) < 4 or cleaned in STOPWORDS or cleaned in seen:
            continue
        seen.append(cleaned)
        if len(seen) >= limit:
            break
    return seen


def _explain(cand, has_hook, has_punch):
    reasons = []
    if has_hook:
        reasons.append("contains a strong hook keyword")
    if has_punch:
        reasons.append("exclamatory/emphatic delivery")
    reasons.append("dense, self-contained phrasing" if cand.get("_density", 0) > 0.6 else "steady, clear pacing")
    return ("Estimated from transcript cues: " + ", ".join(reasons) + ".")[:200]


def select_highlights_heuristic(segments, duration, min_len=15, max_len=90, num_clips=None):
    """Offline fallback: score candidate windows built from consecutive
    transcript segments and greedily pick the best non-overlapping ones.
    Still produces a full SEO metadata set - just via simple text heuristics
    rather than an LLM, so quality is a notch below AI mode."""
    target_n = num_clips or _default_num_clips(duration)
    all_words = [w for s in segments for w in s["words"]]

    candidates = []
    n = len(segments)
    for i in range(n):
        start = segments[i]["start"]
        text_acc = []
        for j in range(i, n):
            end = segments[j]["end"]
            length = end - start
            text_acc.append(segments[j]["text"])
            if length < min_len:
                continue
            if length > max_len:
                break
            joined = " ".join(text_acc)
            candidates.append({"start": start, "end": end, "text": joined, "length": length})
            if length > min_len * 1.6:
                break

    if not candidates:
        step = max(min_len, min(max_len, duration / max(1, target_n)))
        t = 0.0
        while t < duration:
            end = min(duration, t + step)
            start, end = _snap_to_segments(t, end, segments, min_len, max_len)
            candidates.append({"start": start, "end": end, "text": "", "length": end - start})
            t += step

    def score(cand):
        text = cand["text"].lower()
        words = re.findall(r"[a-z']+", text)
        if not words:
            cand["_density"] = 0
            return 0.0
        s = 0.0
        s += text.count("!") * 2.0
        s += text.count("?") * 1.5
        for kw in HOOK_KEYWORDS:
            if kw in text:
                s += 2.5
        non_stop = [w for w in words if w not in STOPWORDS]
        density = len(set(non_stop)) / max(1, len(words))
        cand["_density"] = density
        s += density * 3.0
        filler = sum(words.count(f) for f in ("um", "uh", "like"))
        s -= filler * 0.8
        ideal = (min_len + min(max_len, min_len * 3)) / 2
        s -= abs(cand["length"] - ideal) / max(ideal, 1) * 1.5
        return s

    for c in candidates:
        c["score"] = score(c)

    scores = [c["score"] for c in candidates]
    smin, smax = min(scores), max(scores)

    def normalize(s):
        if smax - smin < 1e-6:
            return 50
        return int(round((s - smin) / (smax - smin) * 100))

    candidates.sort(key=lambda c: c["score"], reverse=True)

    picked = []
    for c in candidates:
        if len(picked) >= target_n:
            break
        overlaps = any(not (c["end"] <= p["end"] and c["start"] >= p["start"]) and
                       not (c["end"] <= p["start"] or c["start"] >= p["end"])
                       for p in picked)
        if overlaps:
            continue
        picked.append(c)
    picked.sort(key=lambda c: c["start"])

    results = []
    for idx, c in enumerate(picked):
        words = _words_in_range(all_words, c["start"], c["end"])
        snippet = c["text"].strip()
        has_hook = any(kw in snippet.lower() for kw in HOOK_KEYWORDS)
        has_punch = ("!" in snippet) or ("?" in snippet)

        title_src = snippet[:70].rsplit(" ", 1)[0] if len(snippet) > 70 else snippet
        title = (title_src or f"Clip {idx + 1}").strip().capitalize()

        tags = _extract_tags(snippet, limit=12)
        hashtags = ["#shorts"] + [f"#{t}" for t in tags[:4]]
        description = (snippet[:260] + ("..." if len(snippet) > 260 else "")).strip()
        if description:
            description += " " + " ".join(hashtags[:4])

        results.append({
            "start": c["start"],
            "end": c["end"],
            "words": words,
            "title": title[:100] or f"Clip {idx + 1}",
            "description": description[:500],
            "tags": tags,
            "hashtags": hashtags[:8],
            "virality_score": normalize(c["score"]),
            "virality_reason": _explain(c, has_hook, has_punch),
        })
    return results


# ------------------------------------------------------------------- entry

def select_highlights(segments, duration, min_len=15, max_len=90, num_clips=None,
                       provider=None, api_key=None, model=None):
    """Entry point used by the pipeline/CLI. Tries AI selection first if a
    provider+key can be resolved from anywhere (explicit args or env/repo
    secrets), transparently falls back to the offline heuristic on any error."""
    resolved_provider, resolved_key = resolve_provider_and_key(provider, api_key)
    if resolved_provider and resolved_key:
        try:
            clips = select_highlights_ai(
                segments, duration, resolved_provider, resolved_key,
                min_len, max_len, num_clips, model,
            )
            return clips, f"ai:{resolved_provider}"
        except Exception:
            pass
    return select_highlights_heuristic(segments, duration, min_len, max_len, num_clips), "heuristic"
