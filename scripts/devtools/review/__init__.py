"""Release 2 agentic-loop review modes: multi-agent, testing and cloud (R2-20 to R2-23).

``dev.py ai review <mode>`` collects bounded, hashed evidence from ``docs/release-2/evidence``
into a deterministic checklist, reviews it through an AI-mode run (or the same loop in-process
with ``--deterministic``) and writes ``reviews/<mode>-review.md`` plus an append-only
``reviews/<mode>-validation-log.jsonl``. ``dev.py ai review decide`` records the human release
decision for the latest cloud review in ``cloud/release-decision.md``.
"""

from scripts.devtools.config import REPOSITORY_ROOT

DEFAULT_EVIDENCE_DIR = REPOSITORY_ROOT / "docs/release-2/evidence"
DECISIONS = ("release", "hold", "rollback")
