"""Slack connector: thread → Document, and private channel → restricted+acl.

Unchanged by the Oracle port — this connector has no database dependency; it
only needs conftest's offline LLM env for enrich_thread() (a no-op offline).
"""

from __future__ import annotations

import os

import pytest

from team_brain.connectors.slack import SlackConnector


def test_export_threads_become_documents(slack_export: str) -> None:
    docs = list(SlackConnector(export_path=slack_export).fetch())
    by_id = {d.external_id: d for d in docs}
    # two public engineering threads + one private security thread
    assert len(docs) == 3

    eng = by_id["C_ENG:1717000000.000100"]
    assert eng.visibility == "public"
    assert eng.acl == []
    assert eng.author == "bob"
    assert "onnxruntime" in eng.body
    assert eng.metadata["channel"] == "engineering"


def test_private_channel_is_restricted_with_member_acl(slack_export: str) -> None:
    docs = list(SlackConnector(export_path=slack_export).fetch())
    private = next(d for d in docs if d.metadata["channel"] == "security-incidents")
    assert private.visibility == "restricted"
    assert private.acl == ["bob"]  # member id resolved to name
    assert "hunter2" in private.body  # secret is IN the body...
    # ...which is exactly why the permission filter (tested elsewhere) matters.


def test_missing_export_raises() -> None:
    with pytest.raises(FileNotFoundError):
        list(SlackConnector(export_path="nope.json").fetch())


def test_live_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("team_brain.connectors.slack.SLACK_BOT_TOKEN", "")
    with pytest.raises(ValueError):
        list(SlackConnector().fetch())


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("TEAMBRAIN_LIVE"), reason="live: set TEAMBRAIN_LIVE=1")
def test_slack_live_smoke() -> None:
    docs = list(SlackConnector().fetch())
    assert isinstance(docs, list)
