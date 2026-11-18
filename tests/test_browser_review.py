"""Real-browser regression for the library, preset editor and photo review workflow."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from image_triage.core.models import Photo
from image_triage.core.settings import load_settings
from image_triage.db.repository import Repository

pytestmark = pytest.mark.skipif(
    not shutil.which("firefox") or not shutil.which("geckodriver"),
    reason="Firefox and geckodriver are needed for the browser workflow test",
)


def _free_port() -> int:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return int(connection.getsockname()[1])


def _wait_for(predicate, timeout: float = 15.0) -> Any:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.1)
    raise AssertionError(f"browser workflow timed out: {last_error}")


def test_browser_preset_and_review_workflow(photo_dir: Path, tmp_path: Path) -> None:
    """Exercise actual browser serialization, JavaScript controls and viewport layout."""
    settings = load_settings(
        None,
        {
            "input": {"root": photo_dir, "db_path": tmp_path / "browser.db"},
            "models": {"enabled": False},
        },
    )
    repository = Repository.open(settings.database_path)
    try:
        repository.sync_roots(settings.watched_roots)
        ids = []
        for name, digest, phash in (
            ("burst_sharp.jpg", "sharp", "0000000000000000"),
            ("burst_soft.jpg", "soft", "0000000000000003"),
            ("burst_blurry.jpg", "blurry", "00000000000000ff"),
        ):
            ids.append(
                repository.upsert_photo(
                    Photo(root_path=str(photo_dir.resolve()), path=name, digest=digest, phash=phash)
                )
            )
        repository.set_groups([(ids[0], 1), (ids[1], 1), (ids[2], 2)])
    finally:
        repository.close()

    server_port, driver_port = _free_port(), _free_port()
    environment = dict(
        os.environ,
        TEST_PHOTO_ROOT=str(photo_dir.resolve()),
        TEST_DATABASE=str(settings.database_path),
        TEST_PORT=str(server_port),
    )
    app_code = """
import os
import uvicorn
from image_triage.core.settings import load_settings
from image_triage.gui.app import create_app
settings = load_settings(None, {
    'input': {'root': os.environ['TEST_PHOTO_ROOT'], 'db_path': os.environ['TEST_DATABASE']},
    'models': {'enabled': False},
})
uvicorn.run(create_app(settings), host='127.0.0.1',
            port=int(os.environ['TEST_PORT']), log_level='warning')
"""
    server = subprocess.Popen(
        [sys.executable, "-c", app_code],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    driver = subprocess.Popen(
        ["geckodriver", "--host", "127.0.0.1", "--port", str(driver_port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    session_id = None
    driver_url = f"http://127.0.0.1:{driver_port}"
    app_url = f"http://127.0.0.1:{server_port}"

    def webdriver(method: str, path: str, data: dict[str, Any] | None = None) -> Any:
        body = json.dumps(data).encode() if data is not None else None
        request = urllib.request.Request(
            driver_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)["value"]
        except urllib.error.HTTPError as exc:
            raise AssertionError(exc.read().decode()) from exc

    def script(source: str) -> Any:
        return webdriver(
            "POST", f"/session/{session_id}/execute/sync", {"script": source, "args": []}
        )

    def navigate(path: str) -> None:
        webdriver("POST", f"/session/{session_id}/url", {"url": app_url + path})

    try:
        for url in (driver_url + "/status", app_url + "/health"):

            def ready(url: str = url) -> bool:
                with urllib.request.urlopen(url, timeout=1):
                    return True

            _wait_for(ready)
        session = webdriver(
            "POST",
            "/session",
            {
                "capabilities": {
                    "alwaysMatch": {
                        "browserName": "firefox",
                        "moz:firefoxOptions": {"args": ["-headless"]},
                    }
                }
            },
        )
        session_id = session["sessionId"]
        webdriver("POST", f"/session/{session_id}/window/rect", {"width": 1366, "height": 768})
        navigate("/settings")
        original_order = script(
            "return Array.from(document.querySelectorAll('[data-preset-row]'))"
            ".map(x => x.dataset.presetName)"
        )
        preset_value_script = (
            "return document.querySelector('[data-preset-name=good] "
            '[aria-label="Preset min_score"]\').value'
        )
        script("document.querySelector('[data-preset-row] [data-move-down]').click()")
        assert (
            script("return document.querySelector('[data-preset-row]').dataset.presetName")
            == original_order[1]
        )
        script("""
            let row = document.querySelector('[data-preset-name="good"]');
            let range = row.querySelector('[data-preset-range] [data-range-min]');
            range.value = '0.72'; range.dispatchEvent(new Event('input'));
            document.querySelector('.settings-actions button').click();
        """)
        _wait_for(lambda: "saved=1" in (script("return location.href") or ""))
        assert script(preset_value_script) == "0.72"
        assert (
            script("return document.querySelector('[data-preset-row]').dataset.presetName")
            == original_order[1]
        )
        script("""
            let row = document.querySelector('[data-preset-name="good"]');
            row.querySelector('[data-clear-range]').click();
            window.beforeSave = true;
            document.querySelector('.settings-actions button').click();
        """)
        _wait_for(lambda: script("return window.beforeSave !== true"))
        assert script(preset_value_script) == ""
        script(
            "window.beforeDelete = true; window.confirm = () => true; "
            "document.querySelector('[data-preset-row] [data-remove-preset]').click()"
        )
        _wait_for(lambda: script("return window.beforeDelete !== true"))
        _wait_for(
            lambda: (
                script("return document.querySelectorAll('[data-preset-row]').length")
                == len(original_order) - 1
            )
        )

        profile_count = script("return document.querySelectorAll('[data-profile-row]').length")
        script(
            "window.beforeDelete = true; window.confirm = () => true; "
            "document.querySelector('[data-remove-profile]').click()"
        )
        _wait_for(lambda: script("return window.beforeDelete !== true"))
        assert (
            script("return document.querySelectorAll('[data-profile-row]').length")
            == profile_count - 1
        )

        navigate("/?view=flat&sort=path&page_size=10")
        script("""
            let slider = document.querySelector('form.filters [name="min_score"]');
            slider.value = '0.42'; slider.dispatchEvent(new Event('input'));
            let name = document.querySelector('[data-save-preset] [name="preset_name"]');
            name.value = 'browser-filter';
            window.beforeCreate = true;
            document.querySelector('[data-save-preset]').requestSubmit();
        """)
        _wait_for(lambda: script("return window.beforeCreate !== true"))
        navigate("/settings")
        assert (
            script(
                "return document.querySelector('[data-preset-name=browser-filter] "
                '[aria-label="Preset min_score"]\').value'
            )
            == "0.42"
        )

        navigate("/?view=flat&sort=path&page_size=10")
        script(
            "document.querySelector('label[for=sidebar-filters]').click(); "
            "document.querySelector('form.filters').requestSubmit()"
        )
        _wait_for(lambda: "tab=filters" in (script("return location.href") or ""))
        assert script("return document.querySelector('#sidebar-filters').checked")
        script("document.querySelector('.card a').click()")
        _wait_for(lambda: "/photo/" in (script("return location.pathname") or ""))
        _wait_for(
            lambda: (script("return document.querySelectorAll('.similarity-card').length") or 0) > 0
        )
        layout = script("""
            let image = document.querySelector('.detail-image').getBoundingClientRect();
            let tile = document.querySelector('.similarity-card').getBoundingClientRect();
            return {height: innerHeight, bottom: image.bottom, tileTop: tile.top};
        """)
        assert layout["bottom"] <= layout["height"] + 1
        assert layout["tileTop"] < layout["height"]
        first_url = script("return location.href")
        script("document.querySelector('.similarity-card a').click()")
        _wait_for(lambda: (href := script("return location.href")) and href != first_url)
        assert "tab=filters" in script("return location.href")
        script(
            "document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'a', bubbles: true}))"
        )
        _wait_for(lambda: script("return !!document.querySelector('.status-accepted')"))
        script("""
            let slider = document.querySelector('[data-similarity-distance]');
            slider.focus();
            slider.dispatchEvent(new KeyboardEvent('keydown', {key: 'r', bubbles: true}));
        """)
        assert script("return !!document.querySelector('.status-accepted')")
        script(
            "document.body.dispatchEvent(new KeyboardEvent('keydown', {key: '4', bubbles: true}))"
        )
        _wait_for(
            lambda: (
                "rating 4/5"
                in (script("return document.querySelector('.review-summary')?.textContent") or "")
            )
        )
        assert "tab=filters" in script("return document.querySelector('[data-back-library]').href")
    finally:
        if session_id:
            try:
                webdriver("DELETE", f"/session/{session_id}")
            except (OSError, AssertionError):
                pass
        for process in (driver, server):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
