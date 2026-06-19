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
             "content": {"question": "Second screen",
                         "options": ["A", "B"], "answer": "A"}},
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
    check("shell renders visual component variants",
          "renderConceptMap" in script and "renderQuiz" in script
          and "content.nodes" in script,
          receipt=script[:500])

    visual = write_modular_site(
        "exp-visual", "job-visual", "Visuals",
        [
            {"id": "trace", "title": "Debug trace",
             "component_type": "flow_diagram",
             "content": {
                 "text": "A CSP-safe SVG flow diagram.",
                 "steps": [
                     {"id": "run", "label": "Run code", "detail": "Start script"},
                     {"id": "bug", "label": "Find bug", "detail": "Trace loop"},
                     {"id": "fix", "label": "Fix bug", "detail": "Patch value"},
                 ],
                 "edges": [
                     {"from": "run", "to": "bug", "label": "reveals"},
                     {"from": "bug", "to": "fix", "label": "leads to"},
                 ],
             }},
            {"id": "timeline", "title": "Story timeline",
             "component_type": "timeline",
             "content": {
                 "events": [
                     {"label": "Lanterns flash", "detail": "Unexpected state"},
                     {"label": "Loop found", "detail": "Root cause"},
                 ],
             }},
        ],
        root=root,
    )
    visual_dir = Path(visual["site_dir"])
    visual_manifest = json.loads((visual_dir / "manifest.json").read_text())
    visual_rep = validate_site(visual_dir)
    visual_script = (visual_dir / "script.js").read_text()
    check("generated diagram site passes validator",
          visual_rep["passed"], receipt="violations=%r" % visual_rep["violations"])
    check("manifest records actual visual components",
          visual_manifest["components_used"] == ["flow_diagram", "timeline"],
          receipt=visual_manifest)
    check("shell includes SVG diagram and timeline renderers",
          "renderDiagram" in visual_script and "renderTimeline" in visual_script
          and "createElementNS" in visual_script,
          receipt=visual_script[:600])

    write_modular_site(
        "exp-mod", "job-mod", "Processes",
        [{"id": "intro", "title": "Intro", "component_type": "recap",
          "content": {"highlights": ["Only screen"]}}],
        root=root,
    )
    check("rewriting a site prunes stale screen files",
          not (site_dir / "screens" / "quiz.json").exists(),
          receipt=list((site_dir / "screens").glob("*.json")))

    safe = write_modular_site(
        "exp-safe", "job-safe", "Safe IDs",
        [
            {"id": "Map scene!", "title": "Map", "component_type": "concept_map",
             "content": {"nodes": [{"label": "A", "detail": "B"}]}},
            {"id": "Map scene!", "title": "Map 2", "component_type": "recap",
             "content": {"highlights": ["C"]}},
        ],
        root=root,
    )
    safe_manifest = json.loads(
        (Path(safe["site_dir"]) / "manifest.json").read_text())
    check("storage normalizes creative model screen ids",
          safe_manifest["screen_order"] == ["Map_scene", "Map_scene_2"],
          receipt=safe_manifest)

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
