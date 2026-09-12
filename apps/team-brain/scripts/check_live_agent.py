"""Live check: the LangChain agent answers as a seeded principal with a real LLM.

Needs an LLM key in the environment or in `.env` (LLM_API_KEY or OPENROUTER_API_KEY).
Runs against the TEST schema and seeds four documents itself.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
os.environ.setdefault("ORACLE_USER", "TEAMBRAIN_TEST")

from team_brain.access import AccessControl, Identity, load_access_spec, seed_access  # noqa: E402
from team_brain.agent import answer  # noqa: E402
from team_brain.config import LLM_BASE_URL, SYNTH_MODEL, has_llm  # noqa: E402
from team_brain.db import DocumentDB  # noqa: E402

print("has_llm:", has_llm(), "| base_url:", LLM_BASE_URL or "(default)", "| model:", SYNTH_MODEL)
db = DocumentDB()
db.init_schema()
ac = AccessControl(db._user, db._password, db._dsn)
seed_access(ac, load_access_spec("data/seed/access.yaml"))
ac.close()

for who, q in [
    (Identity.principal("jeff"), "why is onnxruntime pinned, and who should I ask about it?"),
    (Identity.principal("sam"), "why is onnxruntime pinned?"),
    (Identity.principal("brian"), "what is the status of the Acme deal?"),
]:
    db.set_identity(who)
    res = answer(q, db=db)
    print("\n===", who.value, "|", q)
    print("plan:", res["plan"])
    print("answer:", res["answer"][:600])
    print("citations:", [c["title"] for c in res["citations"]])
    print("experts:", res["experts"])
db.close()
