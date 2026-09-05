# team-brain (Oracle AI Database edition)

**A team knowledge base done right: one shared table, any source plugs in, and the database owns the policy. The team-scale counterpart to a personal Second Brain.**

> Setting this up? Hand this repo to your coding agent. Open the folder in Claude Code (or the agent of your choice) and tell it: *"Read the README and get team-brain running end to end, then wire up the MCP server so I can query it."* It will start the database, bootstrap it, ingest the seed data, seed the access tokens, register the MCP server, and verify everything with `team-brain doctor`. Prefer to do it by hand? Everything it runs is in [Quick start](#quick-start).

team-brain turns messy, multi-source team knowledge (Slack threads, GitHub repos, markdown docs) into one queryable store, and answers questions through **Claude Code via MCP**, a **LangChain agent**, or a thin CLI. It is a compact, working reference implementation of the architecture in Cerebras's [*How We Built Our Knowledge Base*](https://www.cerebras.ai/blog/how-we-built-our-knowledge-base), with the part that write-up leaves open, access control, moved into the database.

## First, the layering: your second brain is *who*, the team brain is *what*

A team knowledge base is not "a second brain for more people." They are two layers doing two different jobs, and you want both.

Your **personal second brain is an agent**: it has a personality, knows you, remembers your context, works proactively, acts on your behalf. One per person. The **team brain is a substrate**: no persona, no memory of you, not proactive. Shared, permissioned, well-ranked knowledge that many agents query. One per team.

It has no personality *on purpose*. Ten people query it through ten different clients; if it synthesized answers it would impose one voice and one interpretation on all ten. So it returns evidence and each person's own agent interprets. That is why the MCP server ships **no `answer()` tool**.

But it is not a passive database either. It owns the **policy**: ingestion, enrichment, retrieval, permissions. You cannot ask every teammate to build hybrid retrieval and fail-closed access control into their own personal setup. Ten implementations means ten sets of bugs and ten chances to leak a private channel. Build it once, every client inherits it.

> **Centralize the policy. Distribute the personality.**
>
> And the most central place for policy is the database itself.

Full argument, including what this rules out and why: **[docs/PERSONAL_VS_TEAM.md](docs/PERSONAL_VS_TEAM.md)**.

## The core idea: meet data where it lives

Every source (Slack, GitHub, docs) becomes a **~40-line connector** that writes rows into **one shared table** in Oracle AI Database. Nothing is forced into a rigid system; a new source plugs in behind the same contract, and everything downstream (search, permissions, the agent, MCP) keeps working unchanged.
-> `team_brain/schema.py` (the contract) - `team_brain/db.py` (the one table) - `team_brain/connectors/` (the plugins)

## What the database does that a vector store cannot

The workshop version of this repo ran on a general-purpose database and did four things in Python that Oracle AI Database does in the table itself:

| Policy | Where it lived | Where it lives now |
|---|---|---|
| **Embeddings** | a local model in the app | `VECTOR_EMBEDDING(...)` is a SQL function. The ONNX model is loaded into the database once; the MERGE that writes a row computes its vector. Text never leaves the database to be embedded. |
| **Keyword + vector search** | two engines, fused in Python | one table: a native `VECTOR` column and an Oracle Text index. Two legs, still fused by rank in Python, or through Oracle's LangChain package. |
| **Who may see what** | a `WHERE` clause the app had to remember | a **row-level policy on the table** (`DBMS_RLS`). Every `SELECT`, from any client, is filtered by the identity on the session. The read code has no permission SQL in it because the filter is not its job. |
| **Identity** | an argument the app passed in | a session property set through a **trusted PL/SQL package** (`tb_session`). The app cannot forge it; the kernel refuses direct writes to the context. A session that never said who it is sees **zero rows**. |

That last row is the one that matters. In the workshop, a caller who held the client config could open a SQL client and read every row. Here the schema owner opening a SQL client sees nothing until it presents a token the database recognises.

## Four policies that make it worth sharing

1. **Enrich before you store.** Slack is mostly noise. We distill each thread to structured knowledge before embedding, so search finds the resolution, not the chatter. -> `team_brain/enrich.py`
2. **Search that actually works.** Vector search alone misses exact strings; keyword search alone misses meaning. Both legs run over the same table and are fused with **Reciprocal Rank Fusion**, plus age decay and a light IDF boost. Legs run through `OracleVS` + `OracleTextSearchRetriever` (Oracle's LangChain package) or as plain SQL; the tests assert they agree. -> `team_brain/retrieval.py`, `team_brain/langchain_legs.py`
3. **Don't build a data leak.** **Label** each document with its domain(s) as it is ingested, then let the database **enforce** at retrieval: a row policy filters every read by the session's identity, before the model sees a row, fail-closed. Someone in ops never sees the sales pipeline, and no prompt can talk the model into it, because the model never receives the row. -> `team_brain/access.py`, `team_brain/db.py`
4. **Primitives, not a magic answer endpoint.** The MCP server exposes `search`, `search_code`, `who_knows`, and `get_document` (full text of one result, since search rows carry a snippet) and returns raw evidence rows. Claude Code orchestrates and synthesizes, so interpretation stays with each caller's own agent. -> `team_brain/mcp_server.py`

## Quick start

```bash
git clone <this repo>
cd team-brain
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

**Local, stdio** (one identity per process): `.mcp.json` in this repo runs the server with a token in `env`. Swap the token to change who Claude Code is.

**Remote service, HTTP** (one identity per request): `uv run team-brain serve` starts the server on `http://127.0.0.1:8765/mcp`. Clients send `Authorization: Bearer <token>`; the client config holds the URL and the token, never the database credential. This is the shape a real deployment takes: the service is the only thing that holds the database password, and it never gets to decide who sees what, because the database decides.

```json
{ "mcpServers": { "team-brain": { "type": "http", "url": "http://127.0.0.1:8765/mcp",
    "headers": { "Authorization": "Bearer tb_ops_jeff_7f3a9c21" } } } }
```

Ask Claude Code "who knows about the batch cluster autoscaler?" and watch it call `who_knows`, then `search`, and cite the rows. Call `whoami` to see the identity the database resolved and how many documents it may read.

## Architecture

```
connectors/*  -> Document rows (the contract)            data stays where it lives
ingest:  enrich -> MERGE (embedding computed IN the database) -> tombstone-missing
documents table: VECTOR column + Oracle Text index + acl/domains/project + row policy
retrieval: vector leg + keyword leg (OracleVS / OracleTextSearchRetriever, or SQL) -> RRF -> age decay
identity:  tb_session (trusted package) -> application context -> row policy on every SELECT
clients:   Claude Code over MCP (stdio or HTTP) | LangChain agent (`team-brain ask`) | CLI
```

## Write your own connector

Add a source by writing one ~40-line connector: implement `fetch()`, register it, `ingest`. See **[docs/WRITE_A_CONNECTOR.md](docs/WRITE_A_CONNECTOR.md)**.

## Prove it works

`uv run team-brain doctor` (see `scripts/validate.py`) runs the static checks, the whole test suite against the test schema, and a real ingest -> ask -> eval with a **permission-leak assertion**. The suite includes a test module that proves the database-level facts: no identity means zero rows, the context cannot be written directly, unknown tokens are refused inside the database, and the LangChain legs match the SQL legs row for row.

## Honest limits

- Tokens are static and stored hashed; a production deployment issues short-lived tokens from an identity provider. The enforcement model does not change.
- Enrichment and the CLI agent call an LLM through an OpenAI-compatible endpoint; without a key both degrade to deterministic offline behaviour.
- Oracle AI Database Free is capped at 2 CPUs, 2 GB RAM, and 12 GB of data. Plenty for a team, not the sizing for a company.
- Vector search here is exact. At scale you add a vector index and over-fetch, because the index builds its candidate set before the row policy filters it.

## License

MIT. Built for a Dynamous community workshop and the accompanying video.
