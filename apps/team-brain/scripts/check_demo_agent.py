"""Live-model check of the demo questions against the DEV schema.

Needs an LLM key in the environment or in `.env` (LLM_API_KEY or OPENROUTER_API_KEY).
Expects the dev schema seeded in README order: markdown, base Slack export,
access seed, domain Slack export.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
os.environ.setdefault("ORACLE_USER", "TEAMBRAIN")

from team_brain.access import Identity  # noqa: E402
from team_brain.agent import answer  # noqa: E402
from team_brain.config import SYNTH_MODEL, has_llm  # noqa: E402
from team_brain.db import DocumentDB  # noqa: E402

print("has_llm:", has_llm(), "| model:", SYNTH_MODEL)
db = DocumentDB()
for who, q in [
    (
        Identity.principal("jeff"),
        "who knows about the batch cluster autoscaler, and what did we decide?",
    ),
    (
        Identity.principal("sam"),
        "what is our enterprise discount ceiling, and who set that policy?",
    ),
    (Identity.principal("jeff"), "what is our enterprise discount ceiling?"),
    (Identity.principal("brian"), "what is our enterprise discount ceiling?"),
]:
    db.set_identity(who)
    res = answer(q, db=db)
    print("\n===", who.value, "|", q)
    print("tools:", res["plan"])
    print("answer:", res["answer"][:700])
    print("experts:", res["experts"])
db.close()
