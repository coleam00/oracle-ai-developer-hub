"""GitHub connector runs against recorded API responses (respx) — plus opt-in live.

Unchanged by the Oracle port — this connector has no database dependency.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import httpx
import pytest
import respx

from team_brain.connectors.github import GitHubConnector

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "github_repo.json").read_text())
REPO = "acme/widgets"
API = "https://api.github.com"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _mount(router: respx.Router) -> None:
    router.get(f"{API}/repos/{REPO}").mock(return_value=httpx.Response(200, json=FIXTURE["repo"]))
    router.get(f"{API}/repos/{REPO}/readme").mock(
        return_value=httpx.Response(
            200,
            json={"content": _b64(FIXTURE["readme_text"]), "html_url": FIXTURE["readme_html_url"]},
        )
    )
    router.get(url__regex=rf"{API}/repos/{REPO}/issues.*").mock(
        return_value=httpx.Response(200, json=FIXTURE["issues"])
    )
    router.get(url__regex=rf"{API}/repos/{REPO}/git/trees/.*").mock(
        return_value=httpx.Response(200, json={"tree": FIXTURE["tree"]})
    )
    for path, blob in FIXTURE["files"].items():
        router.get(url__regex=rf"{API}/repos/{REPO}/contents/{path}.*").mock(
            return_value=httpx.Response(
                200, json={"content": _b64(blob["text"]), "html_url": blob["html_url"]}
            )
        )


def test_github_connector_emits_expected_documents() -> None:
    with respx.mock(assert_all_called=False) as router:
        _mount(router)
        docs = list(GitHubConnector(REPO).fetch())

    by_id = {d.external_id: d for d in docs}
    # README
    assert by_id["readme"].metadata["kind"] == "doc"
    assert "banker's rounding" in by_id["readme"].body
    # issue + PR distinguished
    assert by_id["issue:1"].author == "alice"
    assert by_id["issue:1"].metadata["kind"] == "issue"
    assert by_id["pr:2"].metadata["kind"] == "pr"
    # code chunked, only the .py file (README.md/.txt filtered out)
    code = [d for d in docs if d.metadata.get("kind") == "code"]
    assert code, "expected code chunks"
    assert all(d.metadata["path"] == "src/money.py" for d in code)
    assert any("round_half_even" in d.body for d in code)
    # all documents satisfy the contract basics
    assert all(d.created_at.tzinfo is not None for d in docs)


def test_github_rate_limit_stops_gracefully() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API}/repos/{REPO}").mock(
            return_value=httpx.Response(403, headers={"X-RateLimit-Remaining": "0"}, json={})
        )
        docs = list(GitHubConnector(REPO).fetch())
    assert docs == []  # no crash, just nothing


def test_repo_must_be_owner_slash_name() -> None:
    with pytest.raises(ValueError):
        GitHubConnector("noslash")


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("TEAMBRAIN_LIVE"), reason="live: set TEAMBRAIN_LIVE=1")
def test_github_live_smoke() -> None:
    docs = list(GitHubConnector("coleam00/helpline").fetch())
    assert len(docs) > 5
    assert any(d.metadata.get("kind") == "code" for d in docs)
