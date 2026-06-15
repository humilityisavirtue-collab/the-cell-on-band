"""site_validator.py — the §7.5 / §11 security gate for generated sites.

A generated experience is UNTRUSTED until this passes (handoff §11). It is the
last line before a site is exposed at a public URL, so the checks are deny-by-
evidence: required files present, metadata schema valid, and NO way for the site
to reach remote networks or execute injected code (remote URL literals, XHR/
WebSocket/eval/Function/remote <script>/external <iframe>), references local assets
only, has a viewport,
and respects size caps (§7.5 MVP limits).

validate_site(dir) -> {"passed": bool, "violations": [ {check, detail} ]}.
Pure stdlib + regex. The matching gate (test_site_validator.py) feeds it a
genuinely malicious site, per the verification-debt note — a validator only tested
on clean input is theater.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REQUIRED_FILES = (
    "index.html", "styles.css", "script.js", "metadata.json", "manifest.json")
MANIFEST_KEYS = (
    "experience_id", "job_id", "title", "screen_order", "initial_screen_id",
    "components_used", "checkpoint_rules")
SCREEN_KEYS = ("id", "title", "component_type", "content")
_SCREEN_ID = re.compile(r"^[A-Za-z0-9_-]+$")

# The SECURITY BOUNDARY is a strict allowlist CSP (browser-enforced default-deny),
# NOT the regex denylist below — a denylist loses to obfuscation (window['fet'+'ch'],
# eval(atob(...))). connect-src 'self' allows the modular shell to sync progress
# with this backend while still killing remote egress; script-src 'self' (no
# unsafe-inline/eval/remote) kills injected/eval'd code. The server ALSO sends this
# CSP as a response header (main.py) so a page cannot weaken it; the validator
# requires the page to DECLARE it too (safe if served anywhere).
# Core directives that MUST be exactly these (the egress + code-exec boundary):
REQUIRED_CSP = {
    "default-src": {"'none'"},
    "script-src": {"'self'"},
    "connect-src": {"'self'"},
    "object-src": {"'none'"},
    "frame-src": {"'none'"},
    "base-uri": {"'none'"},
}
# Sources that can never appear in script-src/connect-src/default-src (egress/exec holes)
_FORBIDDEN_CSP_SRC = ("'unsafe-eval'", "'unsafe-inline'", "*", "http:", "https:", "data:")

# The exact policy the server sends as a header on every public experience response
# (main.py). Browser-enforced, page cannot loosen it — THIS is the security boundary.
# style 'unsafe-inline' is the only relaxation (inline CSS is not egress/code-exec; url()
# is still bounded by img-src 'self' data:).
STRICT_CSP_HEADER = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
    "frame-src 'none'; frame-ancestors 'none'; object-src 'none'; "
    "base-uri 'none'; form-action 'none'")

METADATA_KEYS = (
    "experience_id", "job_id", "book_title", "chapter_title", "audience_level",
    "experience_style", "screen_count", "band_room_id",
    "selected_brainstorm_variant", "faithfulness_score", "engagement_score",
    "created_at")

# § 7.5 MVP size caps
MAX_BYTES = {"index.html": 250_000, "styles.css": 250_000, "script.js": 250_000}
MAX_ASSETS_TOTAL = 5 * 1024 * 1024

# forbidden code/markup — network egress + dynamic code execution
_FORBIDDEN = [
    ("remote_script", re.compile(r"<script[^>]+src\s*=\s*[\"']\s*https?:", re.I)),
    ("external_iframe", re.compile(r"<iframe[^>]+src\s*=\s*[\"']\s*https?:", re.I)),
    ("xhr", re.compile(r"\bXMLHttpRequest\b")),
    ("websocket", re.compile(r"\bWebSocket\s*\(")),
    ("eval", re.compile(r"\beval\s*\(")),
    ("function_ctor", re.compile(r"\bnew\s+Function\s*\(|\bFunction\s*\(")),
    ("inline_handler", re.compile(r"\son\w+\s*=\s*[\"']", re.I)),  # onclick= etc.
]

# any external src/href (local-only rule). data: and # are fine.
_EXTERNAL_REF = re.compile(r"(?:src|href)\s*=\s*[\"']\s*(https?:|//)", re.I)
_REMOTE_URL_LITERAL = re.compile(r"(?:https?:|wss?:)?//", re.I)
# local asset refs to existence-check
_LOCAL_REF = re.compile(r"(?:src|href)\s*=\s*[\"']\s*(?!https?:|//|data:|#|mailto:)"
                        r"([^\"'?#]+)", re.I)


# content="..." holds single-quoted CSP keywords ('none','self'), so the value is
# double-quoted and may contain single quotes (and vice-versa) — capture either
# quoting without stopping at an inner quote.
_CSP_META = re.compile(
    r"<meta[^>]+http-equiv\s*=\s*[\"']content-security-policy[\"']"
    r"[^>]+content\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.I)


def parse_csp(content: str) -> dict:
    """CSP string -> {directive: set(sources)}.

    FIRST-wins on duplicate directives — matching the BROWSER (a repeated directive
    is ignored; the first occurrence governs). A last-wins parser desyncs from the
    enforcer: `connect-src *; connect-src 'none'` would look safe to a last-wins
    check while the browser honors the permissive first copy. The allowlist CHECK
    must share the allowlist ENFORCER's semantics or the allowlist is itself
    bypassable (club, 2026-06-14 — the denylist-evasion lesson, one level up)."""
    out: dict[str, set] = {}
    for part in content.split(";"):
        toks = part.split()
        if toks and toks[0].lower() not in out:   # FIRST wins, like the browser
            out[toks[0].lower()] = set(toks[1:])
    return out


def csp_violations(html: str) -> list[str]:
    """Return reasons the page's CSP is missing or too weak to be the boundary.
    Empty list == a CSP strict enough to block egress + injected code exec."""
    m = _CSP_META.search(html)
    if not m:
        return ["csp_missing"]
    content = m.group(1) if m.group(1) is not None else m.group(2)
    csp = parse_csp(content)
    problems = []
    for directive, required in REQUIRED_CSP.items():
        got = csp.get(directive)
        if got is None:
            problems.append("csp_missing_%s" % directive)
        elif got != required:
            problems.append("csp_weak_%s(%s)" % (directive, " ".join(sorted(got))))
    # explicit hole scan on the exec/egress-critical directives
    for directive in ("default-src", "script-src", "connect-src"):
        for src in csp.get(directive, set()):
            if src in _FORBIDDEN_CSP_SRC:
                problems.append("csp_hole_%s_%s" % (directive, src.strip("'")))
    return problems


def validate_site(site_dir) -> dict:
    site = Path(site_dir)
    violations: list[dict] = []

    def add(check, detail):
        violations.append({"check": check, "detail": detail})

    # 1. required files
    present = {}
    for fname in REQUIRED_FILES:
        f = site / fname
        if not f.is_file():
            add("missing_file", fname)
        else:
            present[fname] = f

    # 2. metadata schema
    if "metadata.json" in present:
        try:
            meta = json.loads(present["metadata.json"].read_text(
                encoding="utf-8", errors="replace"))
            missing = [k for k in METADATA_KEYS if k not in meta]
            if missing:
                add("metadata_schema", "missing keys: %s" % ", ".join(missing))
        except Exception as e:
            add("metadata_invalid", type(e).__name__)

    manifest = None
    if "manifest.json" in present:
        try:
            manifest = json.loads(present["manifest.json"].read_text(
                encoding="utf-8", errors="replace"))
            missing = [k for k in MANIFEST_KEYS if k not in manifest]
            if missing:
                add("manifest_schema", "missing keys: %s" % ", ".join(missing))
            order = manifest.get("screen_order")
            if not isinstance(order, list) or not order:
                add("manifest_schema", "screen_order must be a non-empty list")
            elif manifest.get("initial_screen_id") not in order:
                add("manifest_schema", "initial_screen_id not in screen_order")
        except Exception as e:
            add("manifest_invalid", type(e).__name__)

    # 3. size caps
    for fname, cap in MAX_BYTES.items():
        if fname in present and present[fname].stat().st_size > cap:
            add("size_limit", "%s > %d bytes" % (fname, cap))
    assets = site / "assets"
    if assets.is_dir():
        total = sum(p.stat().st_size for p in assets.rglob("*") if p.is_file())
        if total > MAX_ASSETS_TOTAL:
            add("assets_too_large", "%d > %d bytes" % (total, MAX_ASSETS_TOTAL))

    # 4. code/markup scan over html + js (+ css for url() egress)
    blob_parts = []
    for fname in ("index.html", "script.js", "styles.css"):
        if fname in present:
            blob_parts.append(present[fname].read_text(
                encoding="utf-8", errors="replace"))
    blob = "\n".join(blob_parts)
    for name, rx in _FORBIDDEN:
        if rx.search(blob):
            add("forbidden_%s" % name, "matched %s" % rx.pattern)
    if _REMOTE_URL_LITERAL.search(blob):
        add("forbidden_remote_url", "html/css/js contains a remote URL literal")

    # 5. viewport + local-only refs + broken local assets (index.html)
    if "index.html" in present:
        html = present["index.html"].read_text(encoding="utf-8", errors="replace")
        # THE BOUNDARY: a strict allowlist CSP must be declared (and the server
        # enforces the same as a header). Missing/weak CSP -> reject, because the
        # regex denylist above cannot stop obfuscated egress on its own.
        for reason in csp_violations(html):
            add("csp", reason)
        if not re.search(r"<meta[^>]+name\s*=\s*[\"']viewport", html, re.I):
            add("no_viewport", "index.html missing viewport meta")
        if _EXTERNAL_REF.search(html):
            add("external_ref", "index.html references an external src/href")
        for ref in _LOCAL_REF.findall(html):
            target = (site / ref).resolve()
            try:
                target.relative_to(site.resolve())   # no traversal escape (§11)
            except ValueError:
                add("path_traversal", ref)
                continue
            if not target.is_file():
                add("broken_asset", ref)

    if manifest is not None:
        screens = site / "screens"
        if not screens.is_dir():
            add("missing_screens_dir", "screens/")
        else:
            for screen_id in manifest.get("screen_order", []):
                if not isinstance(screen_id, str) or not _SCREEN_ID.match(screen_id):
                    add("screen_path", str(screen_id))
                    continue
                screen_file = screens / ("%s.json" % screen_id)
                if not screen_file.is_file():
                    add("screen_missing", str(screen_file.relative_to(site)))
                    continue
                try:
                    screen = json.loads(screen_file.read_text(
                        encoding="utf-8", errors="replace"))
                except Exception as e:
                    add("screen_invalid", "%s: %s" % (screen_id, type(e).__name__))
                    continue
                missing = [k for k in SCREEN_KEYS if k not in screen]
                if missing:
                    add("screen_schema", "%s missing %s" % (
                        screen_id, ", ".join(missing)))
                if screen.get("id") != screen_id:
                    add("screen_schema", "%s id mismatch" % screen_id)

    return {"passed": len(violations) == 0, "violations": violations}
