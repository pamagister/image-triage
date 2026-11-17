"""Regression tests for read-only, photo-relative similarity suggestions."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from image_triage.core.models import Photo
from image_triage.core.settings import load_settings
from image_triage.db.repository import Repository
from image_triage.gui.app import create_app


def test_live_similarity_is_scoped_ranked_paginated_and_read_only(tmp_path: Path) -> None:
    first, second, disabled = [tmp_path / name for name in ("first", "second", "disabled")]
    for root in (first, second, disabled):
        root.mkdir()
    settings = load_settings(
        None,
        {
            "input": {
                "roots": [first, second, disabled],
                "disabled_roots": [disabled],
                "db_path": tmp_path / "state.db",
            },
            "models": {"enabled": False},
        },
    )
    repository = Repository.open(settings.database_path)
    try:
        repository.sync_roots([first, second, disabled], enabled=[first, second])

        def add(root: Path, path: str, digest: str, phash: str) -> int:
            return repository.upsert_photo(
                Photo(root_path=str(root), path=path, digest=digest, phash=phash)
            )

        source_id = add(first, "source.jpg", "source", "0000000000000000")
        assert add(second, "copy.jpg", "source", "0000000000000000") == source_id
        near_id = add(second, "near.jpg", "near", "0000000000000003")
        add(second, "peer.jpg", "peer", "0000000000000003")
        far_id = add(first, "far.jpg", "far", "00000000000000ff")
        missing_id = add(first, "missing.jpg", "missing", "0000000000000001")
        add(disabled, "disabled.jpg", "disabled", "0000000000000001")
        add(first, "bad-hash.jpg", "bad-hash", "not-a-valid-hash")
        repository.set_groups([(source_id, 1), (near_id, 2), (far_id, 2), (missing_id, 1)])
        with repository.connection:
            repository.connection.execute(
                "UPDATE photo_locations SET available = 0 WHERE photo_id = ?", (missing_id,)
            )
        source = repository.active_location_for_photo(source_id, [str(first)], None)
        assert source is not None and source.location_id is not None
        groups_before = repository.connection.execute(
            "SELECT id, group_id FROM photos ORDER BY id"
        ).fetchall()
    finally:
        repository.close()

    with TestClient(create_app(settings)) as client:
        url = f"/api/photo/{source_id}/similar?location_id={source.location_id}"
        exact = client.get(url + "&distance=0").json()
        assert exact["hash_available"] is True
        assert [item["name"] for item in exact["items"]] == ["copy.jpg"]
        assert exact["items"][0]["identical"] is True

        first_page = client.get(url + "&distance=8&limit=1").json()
        assert [item["name"] for item in first_page["items"]] == ["copy.jpg"]
        cursor = first_page["next_cursor"]
        second_page = client.get(url + f"&distance=8&limit=1&after={cursor}").json()
        assert [item["name"] for item in second_page["items"]] == ["near.jpg"]
        assert second_page["items"][0]["distance"] == 2
        assert second_page["items"][0]["same_group"] is False
        third_page = client.get(
            url + f"&distance=8&limit=1&after={second_page['next_cursor']}"
        ).json()
        assert [item["name"] for item in third_page["items"]] == ["peer.jpg"]
        last_page = client.get(
            url + f"&distance=8&limit=1&after={third_page['next_cursor']}"
        ).json()
        assert [item["name"] for item in last_page["items"]] == ["far.jpg"]
        assert last_page["next_cursor"] is None
        assert client.get(url + "&after=bad").status_code == 400
        assert client.get(url + "&distance=33").status_code == 422
        assert (
            client.get(f"/api/photo/{near_id}/similar?location_id={source.location_id}").status_code
            == 404
        )

        detail = client.get(f"/photo/{source_id}?location_id={source.location_id}")
        assert detail.status_code == 200
        assert "Visual suggestions" in detail.text
        assert "Stored similarity group" in detail.text

        repository = Repository.open(settings.database_path)
        try:
            assert (
                repository.connection.execute(
                    "SELECT id, group_id FROM photos ORDER BY id"
                ).fetchall()
                == groups_before
            )
            with repository.connection:
                repository.connection.execute(
                    "UPDATE photos SET phash = '' WHERE id = ?", (source_id,)
                )
        finally:
            repository.close()
        no_hash = client.get(url + "&distance=32").json()
        assert no_hash["hash_available"] is False
        assert [item["name"] for item in no_hash["items"]] == ["copy.jpg"]
