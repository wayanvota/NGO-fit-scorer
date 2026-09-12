from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).parents[1]
BASE_URL = "http://127.0.0.1:8129"


@pytest.fixture(scope="session", autouse=True)
def app_server():
    data_dir = ROOT / ".data"
    data_dir.mkdir(exist_ok=True)
    database = data_dir / "e2e-fit-scorer.db"
    database.unlink(missing_ok=True)
    log_dir = ROOT / "test-results" / "e2e"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = (log_dir / "server.log").open("w", encoding="utf-8")
    env = {
        **os.environ,
        "ANTHROPIC_API_KEY": "",
        "DATABASE_URL": f"sqlite:///{database}",
        "SECRET_KEY": "e2e-only-session-secret",
        "ALLOWED_EMAIL_DOMAINS": "example.org",
        "INITIAL_ADMIN_EMAILS": "admin@example.org",
        "DEV_AUTH": "true",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8129"],
        cwd=ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("E2E server stopped during startup; see test-results/e2e/server.log")
            try:
                with urllib.request.urlopen(f"{BASE_URL}/api/config", timeout=0.2) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("E2E server did not become ready; see test-results/e2e/server.log")
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        log_file.close()
        database.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def browser():
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True, executable_path=executable or None)
        yield instance
        instance.close()


@pytest.fixture()
def page(browser):
    context = browser.new_context(base_url=BASE_URL)
    assets = {
        "**/react.production.min.js": ROOT / "node_modules/react/umd/react.production.min.js",
        "**/react-dom.production.min.js": ROOT / "node_modules/react-dom/umd/react-dom.production.min.js",
        "**/babel.min.js": ROOT / "node_modules/@babel/standalone/babel.min.js",
        "**/marked.min.js": ROOT / "node_modules/marked/marked.min.js",
    }
    def asset_handler(source: Path):
        def fulfill(route):
            route.fulfill(body=source.read_bytes(), content_type="application/javascript")

        return fulfill

    for pattern, asset in assets.items():
        context.route(pattern, asset_handler(asset))
    context.route(
        "**/fonts.googleapis.com/**",
        lambda route: route.fulfill(body="", content_type="text/css"),
    )
    context.route("**/fonts.gstatic.com/**", lambda route: route.abort())
    current_page = context.new_page()
    yield current_page
    context.close()
