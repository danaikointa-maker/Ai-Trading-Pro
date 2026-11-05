"""FastAPI application: REST + WebSocket gateway for the No7 dashboard.

The Laravel layer described in the architecture document maps onto this module:
authentication, resource endpoints, audit and alert delivery live here. Keeping
it in Python removes a second runtime from the local-first deployment while the
API surface (routes / payloads) stays exactly what a Laravel proxy would serve.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from packages.shared_schemas.settings import get_settings
from services.api_gateway.auth import ensure_demo_user
from services.api_gateway.routes import (
    analysis,
    auth,
    backtest,
    brokers,
    explain,
    market,
    risk,
    signals,
    system,
    trading,
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for module in (auth, system, market, analysis, signals, trading, risk, brokers, backtest, explain, ws):
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
