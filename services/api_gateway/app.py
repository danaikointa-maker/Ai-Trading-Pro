"""FastAPI application: REST + WebSocket gateway for the No7 dashboard.

The Laravel layer described in the architecture document maps onto this module:
authentication, resource endpoints, audit and alert delivery live here. Keeping
it in Python removes a second runtime from the local-first deployment while the
API surface (routes / payloads) stays exactly what a Laravel proxy would serve.
"""
from __future__ import annotations

import hashlib
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from packages.shared_schemas.settings import get_settings
from services.api_gateway.auth import ensure_demo_user
from services.api_gateway.ratelimit import RateLimiter, RateLimitMiddleware, build_store
from services.api_gateway.netutil import parse_networks
from services.api_gateway.security import (SecurityHeadersMiddleware,
                                           parse_origins)
from services.api_gateway.routes import (
    analysis,
    auth,
    backtest,
    bridge,
    brokers,
    datasets,
    explain,
    market,
    risk,
    signals,
    system,
    trading,
    users,
    ws,
)
from services.api_gateway.state import TradingRuntime

DASHBOARD_DIST = Path(__file__).resolve().parents[2] / "apps" / "web-dashboard" / "dist"


def create_app(runtime: TradingRuntime | None = None) -> FastAPI:
    settings = get_settings()
    runtime = runtime or TradingRuntime(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ensure_demo_user(app.state.runtime.db, settings)
        app.state.runtime.start()
        try:
            yield
        finally:
            app.state.runtime.stop()

    app = FastAPI(
        title="No7 AI Trading Pro V1",
        description=("Local-first AI trading platform: multi-timeframe analysis, confluence zones, "
                     "calibrated price forecasts, risk-gated signals and a broker-agnostic execution "
                     "gateway. Educational/demo software — not investment advice."),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.runtime = runtime
    # Added first, so CORS ends up outermost and 429s still carry CORS headers
    # (otherwise the browser reports a network error instead of the real limit).
    rl_cfg = settings.app.get("ratelimit") or {}
    store_path = rl_cfg.get("store_path")
    if store_path:
        store_path = Path(str(store_path))
        if not store_path.is_absolute():
            store_path = settings.root / store_path
    elif rl_cfg.get("store"):
        # Any shared backend needs a file to fall back to, so derive one by default.
        store_path = settings.paths["database"].parent / "ratelimit.sqlite3"
    store, store_status = build_store(rl_cfg, path=store_path)
    limiter = RateLimiter(rl_cfg.get("rules"), store=store)
    # The health endpoint lives on the runtime; hand it what the limiter ended up with
    # so the answer comes from the same object that enforces the limit.
    runtime.ratelimit_status = store_status
    # Health asks the limiter itself how often it had to improvise, so an outage
    # cannot hide behind the configuration chosen at boot.
    runtime.ratelimit = limiter
    app.state.ratelimit = limiter
    trusted = parse_networks(settings.trusted_proxies)
    app.add_middleware(RateLimitMiddleware, limiter=limiter, settings=settings,
                       trusted_proxies=settings.trusted_proxies)
    # An explicit allowlist: the dashboard is same-origin, so nothing needs a wildcard.
    # `*` still works if someone really has a separate front-end host, and health says so.
    cors_origins = parse_origins(settings.cors_origins)
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    # Outermost of the three: security headers must also land on 429s and error bodies.
    sh = settings.security_headers
    app.add_middleware(SecurityHeadersMiddleware, trusted_proxies=trusted,
                       csp_mode=str(sh.get("csp_mode", "enforce")),
                       hsts=bool(sh.get("hsts", True)))
    for module in (auth, system, market, analysis, signals, trading, risk, brokers, backtest,
               datasets, users, bridge, explain, ws):
        app.include_router(module.router)

    @app.get("/api", include_in_schema=False)
    def api_root():
        return {"name": "No7 AI Trading Pro", "version": "V1", "docs": "/api/docs",
                "health": "/api/system/health", "time": time.time()}

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # pragma: no cover - safety net
        try:
            app.state.runtime._log_error(f"http:{request.url.path}", exc)  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass
        return JSONResponse(status_code=500, content={"detail": "internal error", "error": str(exc)})

    if DASHBOARD_DIST.exists() and (DASHBOARD_DIST / "index.html").exists():
        # Assets are served from their real directory; everything else falls back
        # to index.html so the SPA router also works on a hard refresh / deep link.
        if (DASHBOARD_DIST / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=str(DASHBOARD_DIST / "assets")), name="assets")

        @app.get("/sw.js", include_in_schema=False)
        def service_worker():
            """Serve the worker with a cache name derived from the current build.

            A stale worker pinning an old bundle is the classic PWA failure, so the
            version comes from a hash of the built index.html: every new build gets a
            new cache and the old one is deleted on activate.
            """
            sw = (DASHBOARD_DIST / "sw.js").read_text("utf-8")
            index = (DASHBOARD_DIST / "index.html").read_bytes()
            version = hashlib.sha256(index).hexdigest()[:12]
            body = sw.replace("__NO7_VERSION__", version)
            return Response(body, media_type="application/javascript",
                            headers={"Cache-Control": "no-cache, must-revalidate",
                                     "Service-Worker-Allowed": "/"})

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str):
            if full_path.startswith(("api/", "ws")):
                raise HTTPException(status_code=404, detail="not found")
            candidate = (DASHBOARD_DIST / full_path).resolve()
            if full_path and candidate.is_file() and DASHBOARD_DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(DASHBOARD_DIST / "index.html")
    else:
        @app.get("/", include_in_schema=False, response_class=HTMLResponse)
        def placeholder():
            return HTMLResponse(
                "<html><body style='background:#07090c;color:#e8ecf3;font-family:ui-sans-serif;"
                "padding:40px;line-height:1.6'><h1>No7 AI Trading Pro — API is running</h1>"
                "<p>The dashboard bundle was not found at <code>apps/web-dashboard/dist</code>.</p>"
                "<p>Run <code>cd apps/web-dashboard &amp;&amp; npm install &amp;&amp; npm run build</code> "
                "or use the Vite dev server on port 5173, which proxies <code>/api</code> and "
                "<code>/ws</code> to this server.</p>"
                "<p><a style='color:#f5b541' href='/api/docs'>/api/docs</a> · "
                "<a style='color:#f5b541' href='/api/system/health'>/api/system/health</a></p>"
                "</body></html>")
    return app


app = create_app()
