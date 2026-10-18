"""Headers from an untrusted peer are claims, not client identity."""
from dataclasses import replace

import pytest
from starlette.requests import Request

from app import rate_limit
from app.runtime import Runtime, runtime_context


def request(peer, forwarded=None):
    headers = [] if forwarded is None else [(b"x-forwarded-for", forwarded.encode("ascii"))]
    return Request({"type": "http", "client": (peer, 10000) if peer is not None else None,
                    "headers": headers, "method": "GET", "path": "/api/chat"})


def test_untrusted_peer_cannot_choose_an_identity_with_a_forged_header(runtime):
    assert rate_limit.client_ip(request("198.51.100.7", "203.0.113.2")) == "198.51.100.7"


def test_loopback_is_not_implicitly_a_trusted_proxy(runtime):
    assert rate_limit.client_ip(request("127.0.0.1", "203.0.113.2")) == "127.0.0.1"


@pytest.mark.parametrize("chain,want", [
    ("203.0.113.2", "203.0.113.2"),
    ("198.51.100.200, 203.0.113.2", "203.0.113.2"),
    ("203.0.113.2, 10.0.0.2", "203.0.113.2"),
    ("malformed", "127.0.0.1"),
    ("203.0.113.2, bad-hop", "127.0.0.1"),
    ("203.0.113.2," * 100, "127.0.0.1"),
])
def test_configured_proxy_walks_right_to_left_and_bad_chains_fall_back(runtime, chain, want):
    configured = Runtime(replace(runtime.settings, TRUSTED_PROXY_CIDRS=("127.0.0.0/8", "10.0.0.0/8")), model=runtime.model)
    with runtime_context(configured):
        assert rate_limit.client_ip(request("127.0.0.1", chain)) == want


def test_invalid_peer_and_missing_client_do_not_trust_headers(runtime):
    assert rate_limit.client_ip(request(None, "203.0.113.2")) == "unknown"
    assert rate_limit.client_ip(request("not-an-ip", "203.0.113.2")) == "unknown"


def test_ipv6_identity_is_canonical_not_spelling_dependent(runtime):
    assert rate_limit.client_ip(request("2001:0db8:0000:0000:0000:0000:0000:0001")) == "2001:db8::1"
