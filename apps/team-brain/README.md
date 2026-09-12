# team-brain

**A knowledge base for a whole team, where the database decides who sees what.**

This is the team-scale counterpart to a personal second brain. I built the first version with the Dynamous community in a workshop; this version moves the hard part, access control, out of the application and into the database. It runs on Oracle AI Database because that is what I used for the demonstration, and the code targets it directly. The idea is bigger than any one tool, though: one shared table, small connectors per source, hybrid search over the same rows, and a permission model the database enforces instead of the app. Take the structure and the split between the personal agent and the team brain, and build it on whatever you run.

> Setting this up? Open the folder in Claude Code (or the agent of your choice) and say: _"Read the README and get team-brain running end to end, then wire up the MCP server so I can query it."_ Everything it will run is in [Quick start](#quick-start).

## Your second brain is who. The team brain is what.

A personal second brain is an agent. It has a personality, it knows you, it works on your behalf, and only you feed it. A team produces far more than any one person can keep up with, so the team needs something else underneath: a shared, permissioned, well-ranked store that many different agents query. That store has no personality on purpose. If it synthesized answers, it would impose one voice on ten people. So it returns evidence, and each person's own agent does the interpreting.

What the team brain does own is the policy: which sources count, what a messy Slack thread actually meant, what "relevant" means, and who may see what. You cannot ask every teammate to build that into their own setup. Build it once, and every agent inherits it.

Centralize the policy. Distribute the personality. And the most central place for policy is the database.

The long version, including what this rules out, is in [docs/PERSONAL_VS_TEAM.md](docs/PERSONAL_VS_TEAM.md).

## What is in here

- **Connectors** (`team_brain/connectors/`): Slack export, GitHub, markdown docs, and a template. Each one is about forty lines and emits the same `Document` row (`team_brain/schema.py`). Adding a source does not touch anything downstream.
- **One table** (`team_brain/db.py`): text, a native `VECTOR` column, an Oracle Text index, and JSON columns for the access labels, all on the same row. The embedding is computed inside the `MERGE` that writes the row with `VECTOR_EMBEDDING(...)`, so the text never leaves the database to be embedded and there is no embedding service to run.
- **Hybrid search** (`team_brain/retrieval.py`, `team_brain/langchain_legs.py`): a keyword leg and a vector leg over the same rows, through Oracle's LangChain package (`OracleTextSearchRetriever` and `OracleVS`), fused by rank with Reciprocal Rank Fusion plus a light age decay. The tests assert the LangChain legs and the plain SQL legs return the same rows.
- **Labels at ingest, enforcement in the database** (`team_brain/access.py`): every row carries its domains and, for private channels, an ACL. Identity is a property of the database session, set through a trusted PL/SQL package (`tb_session`) from a token the database resolves itself. A `DBMS_RLS` row policy on the table appends the caller's predicate to every `SELECT`, from any client. The read code has no permission SQL in it. A session that never established an identity gets zero rows, and the kernel refuses a direct write to the context.
- **Clients**: an MCP server (`team_brain/mcp_server.py`) that exposes `search`, `search_code`, `who_knows`, and `get_document` and returns evidence rows rather than answers, a LangChain `create_agent` CLI (`team_brain/agent.py`), and a plain CLI.

## Quick start

```bash
git clone https://github.com/oracle-devrel/oracle-ai-developer-hub.git
cd oracle-ai-developer-hub/apps/team-brain
docker compose up -d                    # Oracle AI Database 26ai Free; first boot takes a few minutes
uv sync --extra dev
uv run python scripts/bootstrap_db.py   # app users, grants, and the in-database embedding model

# Ingest some knowledge (offline, no API key: embeddings happen in the database)
uv run team-brain ingest markdown data/seed/docs
uv run team-brain ingest slack --export data/seed/slack_export.json
uv run team-brain ingest github coleam00/helpline      # optional; needs network

# Ask (offline: deterministic extractive answer; with an LLM key: a LangChain agent)
uv run team-brain ask "how do we deploy the billing service?" --user alice

# Measure retrieval quality
uv run team-brain eval

# Access control: label by domain, enforce in the database
uv run team-brain access seed          # seeds Jeff/Julia/Sam/Brian, prints their tokens
uv run team-brain ingest slack --export data/seed/slack_export_domains.json
uv run team-brain whoami --as jeff     # what the DATABASE resolved, and how many rows it may see
uv run team-brain ask "what is our enterprise discount ceiling?" --as jeff   # ops: nothing
uv run team-brain ask "what is our enterprise discount ceiling?" --as sam    # sales: the policy
uv run team-brain ask "what is our enterprise discount ceiling?" --token tb_exec_brian_9d4c7b13
```

The one-liner that shows the lock is on the rows, not in the app:

```sql
-- as the schema owner, in any SQL client, with no identity established
SELECT COUNT(*) FROM documents;   -- 0
```

Pulling `container-registry.oracle.com/database/free` needs a free Oracle account (accept the licence once, then `docker login container-registry.oracle.com`). `gvenzl/oracle-free:23` works with no login; use the regular flavour (not `slim`) so Oracle Text is present, and set `ORACLE_PASSWORD` instead of `ORACLE_PWD`. The test suite uses its own schema (`TEAMBRAIN_TEST`) so it never touches your dev knowledge base.

## Query it from Claude Code (MCP)

Two transports, same tools, same policy.

**Local, stdio** (one identity per process): `.mcp.json` in this folder runs the server with a token in `env`, so open Claude Code in `apps/team-brain` for it to be picked up. Swap the token to change who Claude Code is.

**Remote service, HTTP** (one identity per request): `uv run team-brain serve` starts the server on `http://127.0.0.1:8765/mcp`. Clients send `Authorization: Bearer <token>`. The client config holds the URL and the token, never the database credential. This is the shape a real deployment takes: the service is the only thing that holds the database password, and it never gets to decide who sees what, because the database decides.

```json
{
  "mcpServers": {
    "team-brain": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp",
      "headers": { "Authorization": "Bearer tb_ops_jeff_7f3a9c21" }
    }
  }
}
```

Ask Claude Code "who knows about the batch cluster autoscaler?" and watch it call `who_knows`, then `search`, and cite the rows. Call `whoami` to see the identity the database resolved and how many documents it may read. A request with no token is anonymous: a real identity with no grant that sees company-wide rows only. Over HTTP the server never falls back to its own environment, so a missing header can never inherit the operator's identity.

## How it fits together

```
connectors/*  -> Document rows (the contract)            data stays where it lives
ingest:  enrich -> MERGE (embedding computed IN the database) -> tombstone-missing
documents table: VECTOR column + Oracle Text index + acl/domains/project + row policy
retrieval: vector leg + keyword leg (OracleVS / OracleTextSearchRetriever, or SQL) -> RRF -> age decay
identity:  tb_session (trusted package) -> application context -> row policy on every SELECT
clients:   Claude Code over MCP (stdio or HTTP) | LangChain agent (`team-brain ask`) | CLI
```

## Write your own connector

Implement `fetch()`, register it, run `ingest`. See [docs/WRITE_A_CONNECTOR.md](docs/WRITE_A_CONNECTOR.md).

## Prove it works

`uv run team-brain doctor` (see `scripts/validate.py`) runs the static checks, the whole test suite against the test schema, and a real ingest, ask, and eval with a permission-leak assertion. The suite includes a module that proves the database-level facts: no identity means zero rows, the context cannot be written directly, unknown tokens are refused inside the database, a raw username never sees a domain-labelled row, and the LangChain legs match the SQL legs row for row.

## Honest limits

- Tokens are static, stored as unsalted SHA-256, and printed by `access seed` so you can paste them into a client. A production deployment issues short-lived tokens from an identity provider. The enforcement model does not change.
- The default database password (`TeamBrain123`) and the seeded tokens are demo values. Change both before anything leaves your laptop.
- Single-schema demo: the app connects as the schema owner, who also owns `tb_session` and the policy, so that credential can call `set_ingest` or drop the policy. Production puts the package, policy, and access tables in a separate policy-owner schema and grants the application user `EXECUTE` on `set_principal_by_token` only. The row policy and the fail-closed context are the same either way.
- Enrichment and the CLI agent call an LLM through an OpenAI-compatible endpoint. Without a key both degrade to deterministic offline behaviour, which is also why the test suite runs with no key.
- Oracle AI Database Free is capped at 2 CPUs, 2 GB RAM, and 12 GB of data. Plenty for a team, not the sizing for a company.
- Vector search here is exact. At scale you add a vector index and over-fetch, because the index builds its candidate set before the row policy filters it.

## License

MIT. Built for a Dynamous community workshop and the video that followed it.
