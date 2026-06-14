"""chapter_state.py — ChapterWorkflowState (CHAPTERSTAGE_BACKEND_SPEC.md §6.1).

The state carried across the per-agent stages. Each stage fills its own slot; the
artifact chain is pack -> score -> storyboard -> module (chapterstage_envelopes
KINDS). `status` is the job lifecycle; `log` records which stages actually ran so
the kill test can prove a severed run stalls before `completed`.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict
import operator


class ChapterWorkflowState(TypedDict, total=False):
    job_id: str
    source_ref: str            # which chapter/book (faithfulness root)
    pack: dict                 # knowledge_pack envelope (structure)
    score: dict                # brainstorm_score envelope (brainstorm)
    storyboard: dict           # storyboard envelope (visual)
    module: dict               # module envelope (verifier) — the published result
    status: str                # queued | running | stalled | completed | failed
    log: Annotated[list, operator.add]
