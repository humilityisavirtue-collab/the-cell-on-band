"""test_generation_loop.py — the end-to-end gate the repo was missing.

Proves the generation LOOP actually produces a real, sandbox-safe site from a
chapter: deterministic workflow (no network) -> storyboard -> site_builder ->
publish -> the SAME §11 validator the server enforces says PASS. Runs fully
offline (CHAPTERSTAGE_LLM_PROVIDER=none). Exit 0 = PASS.

Key negative control: a chapter whose text literally contains `fetch(`, `eval(`,
and `<script>` (real for CS books) must STILL publish a valid site — the base64
data island keeps those tokens out of the HTML and textContent rendering keeps
them inert. A naive inline-JSON builder would false-positive here; that's the
exact bug this gate locks down.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["CHAPTERSTAGE_LLM_PROVIDER"] = "none"   # deterministic, offline

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import band_service as bs  # noqa: E402
from app.config import settings  # noqa: E402
from app.services.site_validator import METADATA_KEYS, validate_site  # noqa: E402
from workflows.chapter_graph import ChapterWorkflow  # noqa: E402
from workflows.site_builder import build_site  # noqa: E402

FAILURES, RAN = [], []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if not cond:
        FAILURES.append(name)
        if receipt:
            print("         receipt: %s" % receipt)


CHAPTER = """The Process Concept

A process is a program in execution. It is the unit of work in a modern
operating system. Each process has its own address space, a set of registers,
and a program counter that tracks the next instruction.

Process States

A process moves between states: new, ready, running, waiting, and terminated.
The scheduler decides which ready process runs next on the CPU.

Context Switching

When the CPU switches from one process to another, it saves the old process's
state and loads the new one. This is called a context switch, and it has a
real cost in time. Even a call like fetch(resource) or eval("code") in user
space ultimately becomes scheduled work. <script>alert(1)</script> is just text
to the OS.

Inter-Process Communication

Processes coordinate through shared memory or message passing. The operating
system provides the primitives that make this safe.
"""


def _run_loop(tmp: Path, source_text: str, source_ref: str) -> dict:
    settings.GENERATED_SITE_ROOT = str(tmp)
    band = bs.BandService()
    wf = ChapterWorkflow(band)
    state = wf.run("job-e2e", source_ref, source_text=source_text,
                   params={"audience_level": "beginner",
                           "experience_style": "visual_story",
                           "target_screen_count": 6})
    return state


def main():
    print("test_generation_loop.py — chapter -> validated site (offline)")
    import tempfile
    tmp = Path(tempfile.mkdtemp())

    # ----- the happy path: real chapter -> completed -> published valid site -----
    state = _run_loop(tmp, CHAPTER, "OS Notes ch.3: Processes")
    check("workflow reaches completed", state.get("status") == "completed",
          receipt="status=%s" % state.get("status"))

    pack = state.get("pack", {}).get("pack", {})
    storyboard = state.get("storyboard", {}).get("storyboard", {})
    verdict = state.get("module", {}).get("verdict", {})
    check("structure extracted real sections from the text",
          len(pack.get("sections", [])) >= 2, receipt=str(pack.get("sections")))
    check("storyboard has multiple scenes",
          len(storyboard.get("scenes", [])) >= 3,
          receipt="scenes=%d" % len(storyboard.get("scenes", [])))
    check("verifier passed faithfulness", verdict.get("result") == "PASS",
          receipt=str(verdict))

    # build + publish through the REAL storage+validator path
    from app.services.site_storage import publish_site
    meta = {"experience_id": "exp_e2e", "job_id": "job-e2e",
            "book_title": "OS Notes", "chapter_title": "Processes",
            "band_room_id": getattr(state, "get", lambda *_: None)("band_room_id"),
            "selected_brainstorm_variant": "v1", "created_at": "2026-06-15T00:00:00Z"}
    files = build_site(storyboard, pack, verdict, meta)
    check("builder emitted all 4 required files",
          set(files) == {"index.html", "styles.css", "script.js", "metadata.json"},
          receipt=str(sorted(files)))

    report = publish_site("exp_e2e", files)
    check("published site PASSES the §11 validator", report["passed"],
          receipt=str(report["violations"]))
    check("public_url is set on pass", bool(report["public_url"]),
          receipt=str(report["public_url"]))

    # metadata completeness (validator requires every key)
    meta_json = json.loads(files["metadata.json"])
    missing = [k for k in METADATA_KEYS if k not in meta_json]
    check("metadata.json has every required key", missing == [],
          receipt="missing=%s" % missing)

    # the actual chapter content made it into the site (faithfulness, not lorem)
    idx = files["index.html"]
    check("a real section title appears in the page",
          any(s.split()[0] in idx or s[:12] in idx
              for s in pack.get("sections", []) if s),
          receipt="sections=%s" % pack.get("sections"))

    # ----- NEGATIVE CONTROL: malicious tokens in source must NOT break the site --
    # CHAPTER already contains fetch(, eval(, <script>. Prove the built HTML has
    # neither a raw forbidden token from content nor a literal '<script>alert'.
    check("no raw 'fetch(' leaked into index.html (base64 island holds it)",
          "fetch(" not in idx,
          receipt="found fetch( at %d" % idx.find("fetch("))
    check("no raw 'eval(' leaked into index.html", "eval(" not in idx)
    check("injected '<script>alert' is NOT present as live markup",
          "<script>alert" not in idx)
    # and the validator (the real enforcer) still says PASS on this content
    re_report = validate_site(report["storage_path"])
    check("validator PASSES the site built from code-laden source",
          re_report["passed"], receipt=str(re_report["violations"]))

    print("%d/%d checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — chapter in, validated sandbox-safe site out. The loop "
          "produces a real experience and code-laden source can't break it.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
