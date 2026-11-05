"""Entry point: `python -m services.api_gateway.main` (or uvicorn directly)."""
from __future__ import annotations

import os

import uvicorn

from services.api_gateway.app import create_app


def main() -> None:
    host = os.environ.get("NO7_HOST", "0.0.0.0")
    port = int(os.environ.get("NO7_PORT", "8000"))
    uvicorn.run(create_app(), host=host, port=port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
