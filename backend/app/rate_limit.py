"""App-local independent policies and explicit trusted-proxy identity."""
from ipaddress import IPv6Address, ip_address, ip_network

from fastapi import Request

from .rate_policy import RatePolicy, RateDecision, SlidingWindowLimiter
from .request_guards import GuardFailure
from .runtime import get_runtime


def _address(raw):
    parsed = ip_address(raw)
    return parsed.ipv4_mapped if isinstance(parsed, IPv6Address) and parsed.ipv4_mapped else parsed


def client_ip(request: Request) -> str:
    try:
        peer = _address(request.client.host) if request.client else None
    except (ValueError, TypeError):
        peer = None
    if peer is None:
        return "unknown"
    networks = tuple(ip_network(value) for value in get_runtime().settings.TRUSTED_PROXY_CIDRS)

    def trusted(address):
        return any(address.version == network.version and address in network for network in networks)

    if not trusted(peer):
        return str(peer)
    forwarded = ",".join(request.headers.getlist("x-forwarded-for"))
    if not forwarded or len(forwarded) > 2048:
        return str(peer)
    hops = forwarded.split(",")
    if len(hops) > 16:
        return str(peer)
    try:
        chain = [_address(value.strip()) for value in hops]
    except (ValueError, TypeError):
        return str(peer)
    current = peer
    for address in reversed(chain):
        if not trusted(current):
            break
        current = address
    return str(current)


def rate_limits(policies):
    selected = tuple(dict.fromkeys(policies))
    if not selected or any(not isinstance(policy, RatePolicy) for policy in selected):
        raise ValueError("Invalid endpoint rate policies")

    def dependency(request: Request) -> None:
        runtime = get_runtime()
        if not runtime.settings.RATE_LIMIT_ENABLED:
            return None
        endpoint = getattr(request.scope.get("route"), "path", None) or request.scope["path"]
        endpoint = request.scope.get("method", "GET") + ":" + endpoint
        checked = request.scope.setdefault("turtle_soup_rate_checked", set())
        remaining = tuple(policy for policy in selected if (endpoint, policy) not in checked)
        if not remaining:
            return None
        decision = runtime.limiter.check(client_ip(request), endpoint, remaining)
        if not decision.allowed:
            error = GuardFailure(429, "rate_limited", "请求太频繁，请稍后再试。")
            error.headers = {"Retry-After": str(decision.retryAfterSeconds)}
            raise error
        checked.update((endpoint, policy) for policy in remaining)
        return None

    return dependency


def rate_limit(limit: int, window: float):
    return rate_limits((RatePolicy(f"window:{limit}:{window}", limit, window),))
