"""PWA surface: manifest, icons, service worker and the offline shell.

These run against the built dashboard (`apps/web-dashboard/dist`), so they check the
bundle the browser actually receives — a manifest that points at a missing icon, or a
worker whose cache name never changes, fails here instead of in the field.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

DIST = Path(__file__).resolve().parents[1] / "apps" / "web-dashboard" / "dist"

pytestmark = pytest.mark.skipif(not (DIST / "index.html").exists(),
                                reason="dashboard not built (npm run build)")


def test_manifest_is_served_and_installable(client):
    res = client.get("/manifest.webmanifest")
    assert res.status_code == 200
    manifest = json.loads(res.content)
    assert manifest["name"] and manifest["short_name"]
    assert manifest["start_url"] == "/" and manifest["scope"] == "/"
    assert manifest["display"] in ("standalone", "fullscreen", "minimal-ui")
    assert manifest["theme_color"] == "#07090c"
    assert manifest["lang"] == "th"
    # Chrome's installability check: a 192px and a 512px icon
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert "192x192" in sizes and "512x512" in sizes
    assert any(icon.get("purpose") == "maskable" for icon in manifest["icons"])


@pytest.mark.parametrize("icon", ["icon-192.png", "icon-512.png",
                                  "icon-maskable-512.png", "apple-touch-icon.png"])
def test_every_declared_icon_is_served_as_a_real_png(client, icon):
    res = client.get(f"/{icon}")
    assert res.status_code == 200
    assert res.content[:8] == b"\x89PNG\r\n\x1a\n", f"{icon} is not a PNG"
    body = res.content
    # IHDR carries the dimensions: width/height at bytes 16..24
    width, height = int.from_bytes(body[16:20], "big"), int.from_bytes(body[20:24], "big")
    assert width == height and width >= 180


def test_service_worker_is_served_uncached_with_a_build_version(client):
    res = client.get("/sw.js")
    assert res.status_code == 200
    assert "javascript" in res.headers["content-type"]
    assert res.headers["cache-control"].startswith("no-cache")
    body = res.text
    assert "__NO7_VERSION__" not in body, "the version placeholder must be filled in"
    expected = hashlib.sha256((DIST / "index.html").read_bytes()).hexdigest()[:12]
    assert "no7-shell-" in body and expected in body


def test_worker_never_caches_api_or_websocket_traffic(client):
    body = client.get("/sw.js").text
    # the fetch handler must bail out before any cache lookup for live paths
    assert "url.pathname.startsWith('/api/')" in body
    assert "url.pathname.startsWith('/ws')" in body
    assert "request.mode === 'navigate'" in body


def test_worker_precache_list_all_exists(client):
    body = client.get("/sw.js").text
    core = re.search(r"const CORE = \[(.*?)\]", body, re.S).group(1)
    urls = re.findall(r"'([^']+)'", core)
    assert "/" in urls and "/offline.html" in urls
    for url in urls:
        assert client.get(url).status_code == 200, f"precached {url} is missing"


def test_offline_page_is_served_and_explains_itself(client):
    res = client.get("/offline.html")
    assert res.status_code == 200
    assert "ออฟไลน์" in res.text or "ต่อเซิร์ฟเวอร์ไม่ได้" in res.text
    assert "ลองอีกครั้ง" in res.text


def test_index_html_links_the_manifest_and_the_worker_bundle(client):
    html = client.get("/").text
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert 'rel="apple-touch-icon"' in html
    assert 'name="theme-color"' in html
    # the registration lives in the entry chunk, and only PROD builds keep it
    entry = re.search(r'src="(/assets/index-[^"]+\.js)"', html).group(1)
    bundle = client.get(entry).text
    assert "/sw.js" in bundle
    assert "serviceWorker" in bundle


def test_spa_fallback_still_guards_api_and_ws_paths(client):
    assert client.get("/api/definitely-not-a-route").status_code == 404
    assert client.get("/ws").status_code == 404
    deep = client.get("/system")
    assert deep.status_code == 200 and '<div id="app">' in deep.text
