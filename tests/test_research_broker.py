from __future__ import annotations

import socket

import httpx
import pytest

from firewarning_worker.research_broker import BrokerPolicyError, ResearchBroker

CONTROL_TOKEN = "control-token-for-tests-0000000000000000"  # noqa: S105


def _configure(broker: ResearchBroker) -> str:
    result = broker.configure(
        {
            "control_token": CONTROL_TOKEN,
            "policy": {
                "allowed_domains": ["sources.example"],
                "search_templates": {"search.example": "https://search.example/search?q={query}"},
                "max_fetch_bytes": 65_536,
                "timeout_seconds": 5,
                "pathname_prefix": "firewarning/source-packages/upload-test",
                "upload_grant": "g" * 128,
                "token_endpoint": "https://backend.example/api/v1/admin/blob-upload-token",
                "resource_id": "research-test-0001",
                "maximum_file_size_bytes": 1_048_576,
                "allowed_content_types": ["image/jpeg", "text/html"],
            },
        }
    )
    return str(result["session_token"])


def _public_dns(*_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def test_broker_rejects_domain_outside_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    broker = ResearchBroker(control_token=CONTROL_TOKEN)
    token = _configure(broker)

    with pytest.raises(BrokerPolicyError, match="broker_domain_forbidden"):
        broker.fetch(
            {
                "session_token": token,
                "arguments": {"url": "https://untrusted.example/fire.jpg"},
            },
            broker._session({"session_token": token}),
        )


def test_search_provider_cannot_be_fetched_as_a_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    broker = ResearchBroker(control_token=CONTROL_TOKEN)
    token = _configure(broker)

    with pytest.raises(BrokerPolicyError, match="broker_domain_forbidden"):
        broker.fetch(
            {
                "session_token": token,
                "arguments": {"url": "https://search.example/result-page"},
            },
            broker._session({"session_token": token}),
        )


def test_search_returns_only_allowlisted_source_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    html = b"""
    <a href="https://sources.example/fire">trusted</a>
    <a href="https://untrusted.example/fire">untrusted</a>
    <a href="https://search.example/?uddg=https%3A%2F%2Fsources.example%2Fphoto">redirect</a>
    """
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=html,
            request=request,
        )
    )
    broker = ResearchBroker(control_token=CONTROL_TOKEN, transport=transport)
    token = _configure(broker)
    policy = broker._session({"session_token": token})

    result = broker.search(
        {
            "session_token": token,
            "arguments": {"domain": "search.example", "query": "feu de démonstration"},
        },
        policy,
    )

    assert [link["url"] for link in result["links"]] == [
        "https://sources.example/fire",
        "https://sources.example/photo",
    ]


def test_broker_rejects_private_dns_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    broker = ResearchBroker(control_token=CONTROL_TOKEN)
    token = _configure(broker)

    with pytest.raises(BrokerPolicyError, match="broker_private_address_forbidden"):
        broker.inspect(
            {
                "session_token": token,
                "arguments": {"url": "https://sources.example/fire"},
            },
            broker._session({"session_token": token}),
        )


def test_broker_refuses_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            302,
            headers={"location": "https://sources.example/other"},
            request=request,
        )
    )
    broker = ResearchBroker(control_token=CONTROL_TOKEN, transport=transport)
    token = _configure(broker)

    with pytest.raises(BrokerPolicyError, match="broker_redirect_forbidden"):
        broker.fetch(
            {
                "session_token": token,
                "arguments": {"url": "https://sources.example/fire"},
            },
            broker._session({"session_token": token}),
        )


def test_broker_enforces_streamed_response_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"x" * 65_537,
            request=request,
        )
    )
    broker = ResearchBroker(control_token=CONTROL_TOKEN, transport=transport)
    token = _configure(broker)

    with pytest.raises(BrokerPolicyError, match="broker_response_too_large"):
        broker.fetch(
            {
                "session_token": token,
                "arguments": {"url": "https://sources.example/fire"},
            },
            broker._session({"session_token": token}),
        )


def test_revoked_session_cannot_use_network_tools() -> None:
    broker = ResearchBroker(control_token=CONTROL_TOKEN)
    token = _configure(broker)
    broker.revoke({"control_token": CONTROL_TOKEN, "session_token": token})

    with pytest.raises(BrokerPolicyError, match="broker_session_unauthorized"):
        broker.handle(
            {
                "action": "inspect",
                "session_token": token,
                "arguments": {"url": "https://sources.example/fire"},
            }
        )
