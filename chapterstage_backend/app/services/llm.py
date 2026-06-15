"""llm.py — the single inference seam for the generation loop.

The workflow nodes (workflows/chapter_nodes.py) call complete()/complete_json()
here and nowhere else. Behind this seam: the cell's NimProvider (NVIDIA NIM,
the live-keyed sponsor backend — providers.py) when reachable, else a
DETERMINISTIC fallback derived from the real source text. The fallback is not a
"stub": it extracts actual sections/sentences from the chapter so the loop
produces a real (if plainer) site with NO network — which is what keeps the M3/M4
gates green offline and lets the road-trip demo run without a key.

Provider selection: CHAPTERSTAGE_LLM_PROVIDER (default "none" — deterministic and
OFFLINE so gates never touch the network), CHAPTERSTAGE_LLM_MODEL (default a NIM
70B). The live server opts in by exporting CHAPTERSTAGE_LLM_PROVIDER=nim before
launch; everything else (tests, the M3/M4 gates) gets the deterministic path.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# the cell's provider abstraction (NimProvider/FeatherlessProvider/...)
_CELL = Path("C:/kit.triv")
for _p in (str(_CELL), str(_CELL / "cell")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_PROVIDER_NAME = os.environ.get("CHAPTERSTAGE_LLM_PROVIDER", "none").lower()
_MODEL = os.environ.get("CHAPTERSTAGE_LLM_MODEL", "meta/llama-3.3-70b-instruct")

_provider = None
_provider_tried = False


def _get_provider():
    """Lazily construct the configured provider. Returns None (deterministic
    fallback) if disabled, unimportable, or missing its key — never raises."""
    global _provider, _provider_tried
    if _provider_tried:
        return _provider
    _provider_tried = True
    if _PROVIDER_NAME in ("none", "", "off", "deterministic"):
        return None
    try:
        from cell.providers import get_provider
        _provider = get_provider(_PROVIDER_NAME)
    except Exception:
        _provider = None
    return _provider


def available() -> bool:
    """True iff a real LLM backend is wired (for trace honesty / telemetry)."""
    return _get_provider() is not None


def backend_label() -> str:
    return "%s:%s" % (_PROVIDER_NAME, _MODEL) if available() else "deterministic"


def complete(system: str, user: str, *, max_tokens: int = 1500) -> str:
    """One-shot completion. Returns text, or "" if the provider is absent — the
    caller (nodes) must have a deterministic fallback for the "" case."""
    prov = _get_provider()
    if prov is None:
        return ""
    try:
        resp = prov.generate(system=system,
                             messages=[{"role": "user", "content": user}],
                             model=_MODEL, max_tokens=max_tokens)
        return (resp.text or "").strip()
    except Exception:
        return ""


_JSON_FENCE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


def complete_json(system: str, user: str, *, max_tokens: int = 2000,
                  fallback: dict | None = None) -> dict | None:
    """Completion that must return a JSON object. Parses fenced or bare JSON;
    returns `fallback` (default None) if the provider is absent or the output
    isn't valid JSON. Never raises — a malformed model reply degrades, it does
    not crash the loop."""
    text = complete(system + "\n\nReturn ONLY a JSON object, no prose.",
                    user, max_tokens=max_tokens)
    if not text:
        return fallback
    obj = _extract_json(text)
    return obj if obj is not None else fallback


def _extract_json(text: str) -> dict | None:
    for candidate in (_fenced(text), text):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    # last resort: first {...} span
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[start:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        start = text.find("{", start + 1)
    return None


def _fenced(text: str) -> str | None:
    m = _JSON_FENCE.search(text)
    return m.group(1).strip() if m else None


# ----------------------------------------------------------- deterministic aids
# These give the no-provider path REAL structure from the source, not lorem.

def split_sections(text: str, max_sections: int = 6) -> list[str]:
    """Heuristic section titles from the chapter: heading-like lines, else the
    opening clause of evenly-spaced paragraphs. Always returns >=1."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    heads = [ln for ln in lines
             if len(ln) <= 80 and (ln.isupper() or re.match(r"^(#{1,3}\s|\d+[.)]\s)", ln)
                                   or (ln[:1].isupper() and ln[-1:] not in ".!?"))]
    seen, out = set(), []
    for h in heads:
        key = re.sub(r"^[#\d.)\s]+", "", h).strip()
        if key and key.lower() not in seen:
            seen.add(key.lower())
            out.append(key[:80])
        if len(out) >= max_sections:
            break
    if not out:
        paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
        step = max(1, len(paras) // max_sections) if paras else 1
        for p in paras[::step][:max_sections]:
            clause = re.split(r"[.!?]", p)[0].strip()
            out.append((clause[:70] + "…") if len(clause) > 70 else clause or "Section")
    return out or ["Overview"]


def key_sentences(text: str, n: int = 8) -> list[str]:
    """Pull the n most 'topic-sentence' looking sentences (first of each
    paragraph, length-filtered) — the spine of the deterministic content."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    picks = []
    for p in paras:
        s = re.split(r"(?<=[.!?])\s", p)[0].strip()
        if 30 <= len(s) <= 240:
            picks.append(s)
        if len(picks) >= n:
            break
    if not picks:  # very short / single-block source
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s", text or "") if s.strip()]
        picks = sents[:n]
    return picks or ["This chapter introduces its core ideas."]
