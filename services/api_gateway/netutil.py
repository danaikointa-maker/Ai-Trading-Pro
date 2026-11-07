"""Who is the client, when something sits in front of us?

Two facts decide how the perimeter behaves, and both are easy to get wrong:

* **the client IP** keys the login throttle and the rate limiter. Reading
  `X-Forwarded-For` from anybody lets an attacker rotate the header and get a fresh
  budget per request; ignoring it behind a reverse proxy puts every user in one
  bucket, so one noisy client locks out everyone.
* **the scheme** decides whether HSTS and "secure" links are truthful. Only a proxy
  we trust may tell us the original request was HTTPS.

The rule here: believe forwarding headers *only* from a peer inside the trusted
proxy list, and then take the first hop from the right that is not itself a proxy.
Everything else is the raw socket address.
"""
from __future__ import annotations

import ipaddress
from typing import Any, Iterable

Network = ipaddress.IPv4Network | ipaddress.IPv6Network

DEFAULT_TRUSTED_PROXIES = ("127.0.0.1/32", "::1/128")


def parse_networks(values: Iterable[str] | str | None) -> list[Network]:
    """Parse CIDRs (bare addresses become /32 or /128). Junk is ignored, not fatal."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [part.strip() for part in values.split(",") if part.strip()]
    out: list[Network] = []
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        try:
            out.append(ipaddress.ip_network(text, strict=False))
        except ValueError:
            continue
    return out


def _inside(ip: str, networks: list[Network]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in networks)


def peer_ip(scope: Any) -> str:
    client = scope.get("client") if isinstance(scope, dict) else getattr(scope, "client", None)
    if not client:
        return "unknown"
    host = client[0] if isinstance(client, (tuple, list)) else getattr(client, "host", "unknown")
    return str(host or "unknown")


def _header(scope: Any, name: str) -> str:
    raw = scope.get("headers") if isinstance(scope, dict) else getattr(scope, "headers", None)
    if raw is None and not isinstance(scope, dict):
        raw = scope.headers          # Starlette Request
    if not raw:
        return ""
    want = name.lower().encode()
    for key, value in raw:
        k = key.decode("latin-1") if isinstance(key, bytes) else str(key)
        if k.lower().encode() == want:
            v = value.decode("latin-1") if isinstance(value, bytes) else str(value)
            return v
    return ""


def client_ip(scope: Any, trusted: list[Network] | None = None) -> str:
    """The address to blame: the socket peer, or the first untrusted XFF hop behind a proxy."""
    trusted = trusted if trusted is not None else parse_networks(DEFAULT_TRUSTED_PROXIES)
    peer = peer_ip(scope)
    if not trusted or not _inside(peer, trusted):
        return peer                  # untrusted peer: its XFF is a claim, not a fact
    forwarded = _header(scope, "x-forwarded-for")
    if not forwarded:
        return peer
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    for hop in reversed(hops):        # right to left: the closest hop we cannot vouch for
        if not _inside(hop, trusted):
            try:
                return str(ipaddress.ip_address(hop))
            except ValueError:
                continue
    return peer


def is_secure(scope: Any, trusted: list[Network] | None = None) -> bool:
    """True when the browser really used HTTPS (trusting X-Forwarded-Proto only from a proxy)."""
    scheme = ""
    if isinstance(scope, dict):
        scheme = str(scope.get("scheme") or "")
    else:
        scheme = str(getattr(scope, "url", None).scheme if getattr(scope, "url", None) else "")
    if scheme == "https":
        return True
    trusted = trusted if trusted is not None else parse_networks(DEFAULT_TRUSTED_PROXIES)
    if not _inside(peer_ip(scope), trusted):
        return False                  # any client can send this header; only a proxy may mean it
    return _header(scope, "x-forwarded-proto").split(",")[0].strip().lower() == "https"
