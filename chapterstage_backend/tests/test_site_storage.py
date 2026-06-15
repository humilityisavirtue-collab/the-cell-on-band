"""Phase 2 gate: modular generated site assembly."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.services.site_storage import write_modular_site  # noqa: E402
from app.services.site_validator import validate_site  # noqa: E402

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
    print("test_site_storage.py — modular site assembly")
    root = Path(tempfile.mkdtemp())
    result = write_modular_site(
        "exp-mod", "job-mod", "Processes",
        [
            {"id": "intro", "title": "Intro", "component_type": "text_screen",
             "content": {"text": "First screen"}},
            {"id": "quiz", "title": "Quiz", "component_type": "quiz",
             "content": {"text": "Second screen"}},
        ],
        root=root,
    )
    site_dir = Path(result["site_dir"])
    rep = validate_site(site_dir)
    check("generated modular site passes validator", rep["passed"],
          receipt="violations=%r" % rep["violations"])
    manifest = json.loads((site_dir / "manifest.json").read_text())
    check("manifest records progressive screen order",
          manifest["screen_order"] == ["intro", "quiz"]
          and manifest["initial_screen_id"] == "intro", receipt=manifest)
    html = (site_dir / "index.html").read_text()
    check("index shell does not render all screen content up front",
          "First screen" not in html and "Second screen" not in html,
          receipt=html[:200])
    script = (site_dir / "script.js").read_text()
    check("shell syncs progress through same-origin API",
          "/api/v1/experiences/" in script
          and "credentials: 'same-origin'" in script,
          receipt=script[:300])

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — modular sites render progressively and can resume via "
          "same-origin progress APIs.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
