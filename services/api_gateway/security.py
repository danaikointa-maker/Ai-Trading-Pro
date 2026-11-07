"""Response headers that make the browser do the safe thing.

The dashboard holds a bearer token in `localStorage`, so an injected script is a
credential leak; and it can place orders, so framing it inside another page is a
clickjacking surface. Both are fixed with headers rather than with more JavaScript.

The policy is deliberately tight but boring:
* scripts and styles only from this origin (Vue/Tailwind/ECharts ship as files; the
  only inline styles come from Vue's `:style` bindings, hence 'unsafe-inline' there),
* websockets to this origin (the live feed), images from `data:` (the inline favicon),
* no framing, no plugins, no base-tag rewriting.

`app.security_headers.csp_mode` can be `enforce`, `report` (header becomes
Report-Only, nothing breaks while you look at the console) or `off`. Default is
`enforce`: a policy nobody enforces is only decoration.
"""
from __future__ import annotations

from typing import Any, Iterable

from services.api_gateway.netutil import is_secure, parse_networks

CSP = "; ".join((
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    "connect-src 'self' ws: wss:",
    "worker-src 'self'",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
))

# Swagger UI (/api/docs) is the one page that legitimately needs a CDN: FastAPI serves
# its HTML, but the bundle comes from jsDelivr and the page uses an inline init script.
# Scoping the exception to that path keeps the dashboard policy strict.
DOCS_CSP = "; ".join((
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.jsdelivr.net",
    "font-src 'self' data: https://cdn.jsdelivr.net",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
))
DOCS_PREFIXES = ("/api/docs", "/api/redoc")

# Applies to every response: cheap, and missing on one path is missing everywhere.
BASE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}

# Only sent over HTTPS: over plain HTTP the browser would cache the upgrade and brick
# the plain-HTTP dev setup, and claiming HTTPS when we are not is worse than silence.
HSTS = "max-age=15552000; includeSubDomains"


class SecurityHeadersMiddleware:
    """ASGI middleware: append the perimeter headers to every HTTP response."""

    def __init__(self, app: Any, *, trusted_proxies: Iterable[str] | None = None,
                 csp_mode: str = "enforce", hsts: bool = True,
                 csp: str | None = None) -> None:
        self.app = app
        self.trusted = parse_networks(list(trusted_proxies or []))
        self.csp_mode = csp_mode if csp_mode in ("enforce", "report", "off") else "enforce"
        self.hsts = hsts
        self.csp = csp or CSP

    def _headers_for(self, scope: Any) -> list[tuple[bytes, bytes]]:
        out = [(k.lower().encode(), v.encode()) for k, v in BASE_HEADERS.items()]
        if self.csp_mode != "off":
            name = ("content-security-policy" if self.csp_mode == "enforce"
                    else "content-security-policy-report-only")
            path = str(scope.get("path") or "")
            policy = DOCS_CSP if path.startswith(DOCS_PREFIXES) else self.csp
            out.append((name.encode(), policy.encode()))
        if self.hsts and is_secure(scope, self.trusted):
            out.append((b"strict-transport-security", HSTS.encode()))
        return out

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        extra = self._headers_for(scope)

        async def _send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {k.lower() for k, _ in headers}
                headers.extend((k, v) for k, v in extra if k not in present)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, _send)


def parse_origins(values: Any) -> list[str]:
    """Normalise the CORS allowlist; `*` survives because it is a deliberate choice."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [part.strip() for part in values.split(",")]
    out = []
    for raw in values:
        text = str(raw).strip().rstrip("/")
        if text and text not in out:
            out.append(text)
    return out


def is_wildcard(origins: list[str]) -> bool:
    return "*" in origins
