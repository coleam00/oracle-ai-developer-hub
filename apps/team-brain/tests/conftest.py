"""Shared test fixtures (Oracle AI Database edition).

Everything runs against the disposable TEAMBRAIN_TEST schema in the
`team-brain-oracle` Oracle AI Database Free container (localhost:1521,
service FREEPDB1). We point ORACLE_USER at that schema BEFORE importing
team_brain so config.py picks it up, force the LLM offline for determinism
(unless TEAMBRAIN_LIVE), and truncate between tests for isolation.

Identity lives in the DATABASE (see team_brain/access.py), not in Python, so
these fixtures hand out `Identity` values (or a seeded {username: token} map)
rather than raw usernames + domain lists the way the Postgres edition did.
"""

from __future__ import annotations

import os

# Must happen before any team_brain import so config picks these up.
os.environ["ORACLE_USER"] = "TEAMBRAIN_TEST"
os.environ.setdefault("ORACLE_PASSWORD", "TeamBrain123")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
if not os.environ.get("TEAMBRAIN_LIVE"):
    os.environ["LLM_API_KEY"] = ""
    os.environ["OPENROUTER_API_KEY"] = ""
    os.environ["OPENAI_API_KEY"] = ""

import time  # noqa: E402
from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402

from team_brain.access import AccessControl, Identity, load_access_spec, seed_access  # noqa: E402
from team_brain.config import REPO_DIR  # noqa: E402
from team_brain.db import DocumentDB  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema() -> None:
    """Wait for the test schema and create the schema objects once per session.

    DocumentDB.init_schema() creates the documents table, the Oracle Text
    index, the identity admin tables, the trusted tb_session package, and the
    row policy — everything AccessControl needs too.
    """
    last: Exception | None = None
    for _ in range(30):
        try:
            d = DocumentDB()
            d.init_schema()
            d.close()
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2)
    pytest.exit(f"test schema TEAMBRAIN_TEST not reachable at localhost:1521/FREEPDB1: {last}")


@pytest.fixture
def db() -> Iterator[DocumentDB]:
    """A clean DocumentDB (table truncated) with INGEST identity for one test.

    INGEST mode sees every row (no policy predicate), which is what most
    tests want by default: seed data, then read it back. Tests that assert
    the permission/domain leak matrix explicitly switch identity via
    `db.set_identity(...)` before reading.
    """
    d = DocumentDB()
    d.init_schema()
    d.set_identity(Identity.ingest())
    d.truncate()
    d.commit()
    yield d
    d.close()


@pytest.fixture
def seed_docs() -> str:
    return str(REPO_DIR / "data" / "seed" / "docs")


@pytest.fixture
def slack_export() -> str:
    return str(REPO_DIR / "data" / "seed" / "slack_export.json")


@pytest.fixture
def domain_slack_export() -> str:
    return str(REPO_DIR / "data" / "seed" / "slack_export_domains.json")


@pytest.fixture
def access_spec_path() -> str:
    return str(REPO_DIR / "data" / "seed" / "access.yaml")


@pytest.fixture
def tokens(access_spec_path: str) -> dict[str, str]:
    """Seed principals/groups/tokens into the test schema; return {username: token}."""
    ac = AccessControl()
    try:
        ac.init_schema()
        result = seed_access(ac, load_access_spec(access_spec_path))
    finally:
        ac.close()
    return result


@pytest.fixture
def alice() -> Identity:
    """Raw `user` identity (ACL-only, no domain grant) — the legacy `--user` path."""
    return Identity.user("alice")


@pytest.fixture
def bob() -> Identity:
    return Identity.user("bob")
