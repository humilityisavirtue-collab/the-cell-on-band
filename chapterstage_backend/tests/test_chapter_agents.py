"""Phase 5 gate: provider-backed agent bodies with deterministic fallback."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.services import chapter_agents  # noqa: E402

FAILURES: list[str] = []
RAN: list[str] = []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if receipt and not cond:
        print("         receipt: %s" % receipt)
    if not cond:
        FAILURES.append(name)


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def generate_json(self, messages, schema, model=None):
        if "structure" in messages[0]["content"]:
            return {"sections": ["A", "B"], "ideas": ["I1"]}
        if "Score" in messages[0]["content"]:
            return {"variant_id": "v9", "metric": "clarity", "value": 0.91}
        if "storyboard" in messages[0]["content"]:
            return {"scenes": [{"id": 7, "kind": "quiz"}]}
        return {"result": "PASS", "receipts": "fake receipts"}


def clear_provider_env():
    for key in list(os.environ):
        if key.startswith(("OLLAMA_", "OPENAI_", "ANTHROPIC_", "FEATHERLESS_")) \
                or key == "LLM_PROVIDER":
            os.environ.pop(key)


def main():
    print("test_chapter_agents.py — provider-backed agent bodies")
    clear_provider_env()
    state = {"source_ref": "ch1", "source_text": "source text"}
    pack = chapter_agents.build_structure_pack(state)
    check("deterministic fallback produces valid pack",
          pack["source_ref"] == "ch1" and pack["sections"] and pack["ideas"],
          receipt=pack)

    original_create = chapter_agents.create_provider
    try:
        os.environ["OLLAMA_MODEL"] = "fake-local"
        chapter_agents.create_provider = lambda: FakeProvider()
        pack = chapter_agents.build_structure_pack(state)
        score = chapter_agents.build_brainstorm_score({"pack": pack})
        storyboard = chapter_agents.build_storyboard({"pack": pack, "score": score})
        verdict = chapter_agents.build_verifier_verdict({"storyboard": storyboard})
    finally:
        chapter_agents.create_provider = original_create
        clear_provider_env()

    check("configured provider supplies structure output",
          pack["sections"] == ["A", "B"] and pack["ideas"] == ["I1"], receipt=pack)
    check("configured provider supplies brainstorm score",
          score["variant_id"] == "v9" and score["value"] == 0.91, receipt=score)
    check("configured provider supplies storyboard",
          storyboard["scenes"][0]["kind"] == "quiz", receipt=storyboard)
    check("configured provider supplies verifier verdict",
          verdict["result"] == "PASS" and verdict["receipts"] == "fake receipts",
          receipt=verdict)

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — agent bodies use configured providers and keep an "
          "offline deterministic fallback.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
