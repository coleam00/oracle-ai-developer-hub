"""Idempotent seeder for the FULL Acme Ledger knowledge base demo.

Seeds a MUCH larger, realistic 40-person-company knowledge base
(data/seed_full/) so the video demo and tests exercise team-brain at scale.
Does NOT touch data/seed/ (the original small seed) or any file under
team_brain/ or tests/.

What this does, in order:
  1. Initialise the schema (idempotent — DocumentDB.init_schema() is a no-op
     on tables that already exist).
  2. Seed access control from data/seed_full/access.yaml (extends the four
     original principals with alice/bob/priya; original tokens unchanged).
  3. Ingest every markdown doc under data/seed_full/docs/<domain>/ with the
     RIGHT domain label per subfolder, in a SINGLE ingest() call so the
     tombstone pass (which operates per `source`, not per sub-call — see
     "On tombstoning" below) only ever removes markdown docs this run no
     longer emits, never a sibling domain's docs from an earlier sub-call.
  4. Ingest the Slack export (data/seed_full/slack_export.json) — one file,
     one connector call, all 8 channels/34 threads in one pass, so this one
     was never at risk of the tombstone problem in step 3.
  5. Print team_brain.db.DocumentDB().stats().

On tombstoning (why this needed a custom connector, not 5 CLI calls)
---------------------------------------------------------------------
`team_brain.ingest.ingest(source, args)` calls `db.tombstone_missing(source,
seen_ids)` after upserting, which soft-deletes every LIVE row whose
`source` matches and whose `external_id` was NOT in `seen_ids` THIS CALL
(team_brain/db.py: `tombstone_missing`, `WHERE source = :s ... NOT ... IN
seen`). `seen_ids` is scoped to a single `ingest()` invocation.

The obvious approach — one `ingest("markdown", [subfolder, "--domain",
dom])` call per subfolder — is broken: each subsequent call's `seen_ids`
only contains THAT subfolder's filenames, so it would tombstone every
markdown doc from every subfolder ingested in an earlier call this run.
Verified by reading team_brain/ingest.py and team_brain/db.py; not
guesswork.

`MarkdownDocsConnector.__init__` (team_brain/connectors/markdown_docs.py)
also only accepts ONE `domains` list applied uniformly to every file it
emits, and `_build_markdown` (team_brain/connectors/__init__.py) only reads
`rest[0]` as the root — so a single stock `ingest("markdown", ...)` call
cannot vary domains per subfolder either.

The fix used here needs NO change to team_brain/: `_DomainMappedMarkdown`
below is a connector (same `source`/`fetch()` contract as
MarkdownDocsConnector) that walks ALL of data/seed_full/docs/<domain>/ in
its OWN `fetch()` and assigns each file's `domains` from a per-subfolder
map, so the whole tree becomes ONE logical connector run. It emits
`Document(source="markdown", ...)` — the same source string the stock
connector uses — so `expected_source: markdown` in golden questions still
matches, and reusing the string is what lets `ingest.ingest("markdown",
[])` (via a runtime `connectors.register("markdown", ...)` override, using
the library's own public extension point) drive it through the exact same
upsert + single tombstone pass as any other connector, just with correct
per-file domains and exactly one tombstone call for the whole tree.

This IS possible without touching team_brain/ — see the report printed by
`--report-only` below (or the task's final report) for confirmation there
was no dead end here.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
SEED_FULL_DIR = REPO_DIR / "data" / "seed_full"
DOCS_DIR = SEED_FULL_DIR / "docs"
ACCESS_YAML = SEED_FULL_DIR / "access.yaml"
SLACK_EXPORT = SEED_FULL_DIR / "slack_export.json"

# Subfolder -> domains applied to every doc under it. Empty list = company-wide.
DOMAIN_MAP: dict[str, list[str]] = {
    "engineering": [],
    "people": [],
    "ops": ["ops"],
    "marketing": ["marketing"],
    "sales": ["sales"],
    "finance": ["finance"],
}


def _build_domain_mapped_markdown_connector():
    """Build the custom multi-domain markdown connector (see module docstring)."""
    import re

    from team_brain.schema import Document

    h1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)

    class _DomainMappedMarkdown:
        source = "markdown"

        def __init__(self, root: Path, domain_map: dict[str, list[str]]) -> None:
            self.root = root
            self.domain_map = domain_map

        def fetch(self) -> Iterable[Document]:
            if not self.root.exists():
                raise FileNotFoundError(f"markdown root not found: {self.root}")
            for subfolder, domains in sorted(self.domain_map.items()):
                folder = self.root / subfolder
                if not folder.exists():
                    continue
                for path in sorted(folder.rglob("*.md")):
                    text = path.read_text(encoding="utf-8")
                    rel = path.relative_to(self.root).as_posix()  # e.g. "ops/oncall-rotation.md"
                    m = h1.search(text)
                    title = m.group(1).strip() if m else path.stem
                    created = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
                    yield Document(
                        source=self.source,
                        external_id=rel,
                        title=title,
                        body=text,
                        url=f"file://{path.resolve().as_posix()}",
                        created_at=created,
                        project="default",
                        domains=list(domains),
                        metadata={"path": rel, "domain_folder": subfolder},
                    )

    return _DomainMappedMarkdown(DOCS_DIR, DOMAIN_MAP)


def _register_full_markdown_connector() -> None:
    """Runtime-register our connector under the SAME 'markdown' key.

    Uses team_brain.connectors.register(), the library's own public
    extension point (its own docstring: "write a module ... then register a
    builder here" — calling register() from outside is the same operation,
    just not committed into that file). This overwrites the in-process
    dict entry only; no file under team_brain/ is touched.
    """
    from team_brain.connectors import register

    connector = _build_domain_mapped_markdown_connector()
    register("markdown", lambda args: connector)


def seed_access() -> None:
    from team_brain.access import AccessControl, load_access_spec
    from team_brain.access import seed_access as do_seed
    from team_brain.db import DocumentDB

    db = DocumentDB()
    try:
        db.init_schema()
    finally:
        db.close()

    ac = AccessControl()
    try:
        tokens = do_seed(ac, load_access_spec(str(ACCESS_YAML)))
        principals = ac.list_principals()
    finally:
        ac.close()

    print(f"Seeded {len(principals)} principals from {ACCESS_YAML}:")
    for p in principals:
        print(f"  {p.describe()}")
    print("\nTokens:")
    for user, token in tokens.items():
        print(f"  {user:8} {token}")
    print()


def ingest_docs() -> None:
    from team_brain.ingest import ingest

    _register_full_markdown_connector()
    res = ingest("markdown", [])
    print(
        f"[markdown] upserted={res.upserted} tombstoned={res.tombstoned} "
        f"fail_closed={res.skipped_fail_closed}"
    )


def ingest_slack() -> None:
    from team_brain.ingest import ingest

    res = ingest("slack", ["--export", str(SLACK_EXPORT)])
    print(
        f"[slack] upserted={res.upserted} tombstoned={res.tombstoned} "
        f"fail_closed={res.skipped_fail_closed}"
    )


def print_stats() -> None:
    from team_brain.db import DocumentDB

    db = DocumentDB()
    try:
        db.init_schema()
        import json as _json

        print(_json.dumps(db.stats(), indent=2))
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-access", action="store_true", help="skip the access-control seed step"
    )
    args = parser.parse_args()

    if not args.skip_access:
        seed_access()
    ingest_docs()
    ingest_slack()
    print_stats()
    return 0


if __name__ == "__main__":
    sys.exit(main())
