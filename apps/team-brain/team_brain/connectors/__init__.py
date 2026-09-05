"""Connector registry.

Maps a source name to a builder that turns CLI args into a Connector instance.
To add a source: write a module with a class exposing `source` + `fetch()`,
then register a builder here.
"""

from __future__ import annotations

from collections.abc import Callable

from team_brain.connectors.base import Connector, Document

# name -> (args -> Connector)
CONNECTOR_BUILDERS: dict[str, Callable[[list[str]], Connector]] = {}


def register(name: str, builder: Callable[[list[str]], Connector]) -> None:
    CONNECTOR_BUILDERS[name] = builder


def build_connector(name: str, args: list[str]) -> Connector:
    if name not in CONNECTOR_BUILDERS:
        raise KeyError(f"unknown connector {name!r}; registered: {sorted(CONNECTOR_BUILDERS)}")
    return CONNECTOR_BUILDERS[name](args)


def registered() -> list[str]:
    return sorted(CONNECTOR_BUILDERS)


def _pop_domains(args: list[str]) -> tuple[list[str], list[str]]:
    """Extract `--domain X` / `--domains a,b,c` from args; return (domains, rest).

    Domains are the group-based access labels applied to every document this
    connector emits (e.g. `ingest markdown data/seed/domains/ops --domain ops`).
    """
    domains: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(args):
        if args[i] in ("--domain", "--domains") and i + 1 < len(args):
            domains.extend(d.strip() for d in args[i + 1].split(",") if d.strip())
            i += 2
        else:
            rest.append(args[i])
            i += 1
    return domains, rest


# --- markdown (reference) ---
def _build_markdown(args: list[str]) -> Connector:
    from team_brain.connectors.markdown_docs import MarkdownDocsConnector

    domains, rest = _pop_domains(args)
    root = rest[0] if rest else "data/seed/docs"
    return MarkdownDocsConnector(root, domains=domains)


register("markdown", _build_markdown)


# --- github ---
def _build_github(args: list[str]) -> Connector:
    from team_brain.connectors.github import GitHubConnector

    domains, rest = _pop_domains(args)
    if not rest:
        raise ValueError("github connector needs a repo, e.g. `ingest github owner/repo`")
    return GitHubConnector(rest[0], domains=domains)


register("github", _build_github)


# --- slack ---
def _build_slack(args: list[str]) -> Connector:
    from team_brain.connectors.slack import SlackConnector

    # `ingest slack --export path.json`  or  `ingest slack` (live via SLACK_BOT_TOKEN)
    export = None
    if args and args[0] == "--export" and len(args) > 1:
        export = args[1]
    return SlackConnector(export_path=export)


register("slack", _build_slack)


# --- template (workshop stub) ---
def _build_template(args: list[str]) -> Connector:
    from team_brain.connectors.TEMPLATE import MyConnector

    return MyConnector()


register("template", _build_template)


__all__ = [
    "Connector",
    "Document",
    "CONNECTOR_BUILDERS",
    "register",
    "build_connector",
    "registered",
]
