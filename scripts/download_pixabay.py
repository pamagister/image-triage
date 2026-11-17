#!/usr/bin/env python3
"""Download photos from Pixabay in multiple categories with credits and compression.

Requires a free Pixabay API key (https://pixabay.com/api/docs/), passed either
via the ``--api-key`` option or the ``PIXABAY_API_KEY`` environment variable.

Usage::

    export PIXABAY_API_KEY="your-key"
    uv run python scripts/download_pixabay.py --count-per-category 10

The images are resized to max 1600 px and compressed to max 200 KB, then stored
in ``images/pixabay/`` together with a ``credits.md`` listing author, source URL
and licence for every downloaded file.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

API_BASE = "https://pixabay.com/api/"
OUTPUT_DIR_NAME = "pixabay"
CREDITS_FILE = "credits.md"
REQUEST_DELAY_S = 0.2
USER_AGENT = "image-triage-download-script/1.0"
MAX_DIMENSION = 1600
MAX_FILE_SIZE_BYTES = 200 * 1024  # 200 KB

DEFAULT_CATEGORIES = [
    "animals",
    "landscape",
    "technology",
    "architecture",
    "food",
    "people",
    "sports",
    "travel",
    "business",
    "nature",
    "group",
]


def slugify(text: str, max_len: int = 40) -> str:
    """Turn a string into a filesystem-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len] or "photo"


def fetch_json(url: str, timeout: int = 30) -> dict[str, Any]:
    """GET ``url`` and return the parsed JSON response."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Pixabay API returned HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach Pixabay API: {exc}") from exc
    return json.loads(body.decode("utf-8"))


def resize_and_compress(image: Image.Image) -> bytes:
    """Resize to max dimension and compress JPEG to stay under MAX_FILE_SIZE_BYTES."""
    img = image.convert("RGB")
    width, height = img.size
    if max(width, height) > MAX_DIMENSION:
        scale = MAX_DIMENSION / max(width, height)
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    for quality in (90, 85, 80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30):
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        data = buffer.getvalue()
        if len(data) <= MAX_FILE_SIZE_BYTES:
            return data

    # Fallback: lowest acceptable quality
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=30, optimize=True)
    return buffer.getvalue()


def download_image_bytes(url: str, timeout: int = 60) -> bytes:
    """Download a single image from ``url`` and return its raw bytes."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Download of {url} failed with HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Download of {url} failed: {exc}") from exc


def fetch_hits(
    api_key: str,
    query: str,
    count: int,
    per_page: int = 100,
) -> list[dict[str, Any]]:
    """Fetch ``count`` photo hits from the Pixabay API in pages."""
    hits: list[dict[str, Any]] = []
    page = 1
    while len(hits) < count:
        params = {
            "key": api_key,
            "q": query,
            "image_type": "photo",
            "per_page": min(per_page, count - len(hits)),
            "page": page,
            "safesearch": "true",
        }
        url = API_BASE + "?" + urllib.parse.urlencode(params)
        data = fetch_json(url)
        page_hits = data.get("hits", [])
        if not page_hits:
            break
        hits.extend(page_hits)
        total = data.get("total", 0)
        if len(hits) >= total or page * per_page >= total:
            break
        page += 1
        time.sleep(REQUEST_DELAY_S)
    return hits[:count]


def write_credits(images_dir: Path, records: list[dict[str, str]]) -> None:
    """Write ``credits.md`` next to the downloaded images."""
    lines: list[str] = [
        "# Pixabay Image Credits",
        "",
        "Source: https://pixabay.com/",
        "Licence: Pixabay License (free for commercial use, no attribution required, "
        "but appreciated).",
        "",
        "| Category | File | ID | Author | Author URL | Image URL | Page URL | Tags |",
        "| -------- | ---- | -- | ------ | ---------- | --------- | -------- | ---- |",
    ]
    for rec in records:
        row = (
            "| {category} | {file} | {id} | {author} | {author_url} | "
            "{image_url} | {page_url} | {tags} |"
        ).format(**rec)
        lines.append(row)
    lines.append("")
    (images_dir / CREDITS_FILE).write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download photos from Pixabay in categories with credits."
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("PIXABAY_API_KEY"),
        help="Pixabay API key (or set PIXABAY_API_KEY env var)",
    )
    parser.add_argument(
        "--categories",
        default=",".join(DEFAULT_CATEGORIES),
        help="Comma-separated list of search categories",
    )
    parser.add_argument(
        "--count-per-category",
        type=int,
        default=10,
        help="Number of photos per category (default: 10)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Destination folder (default: images/pixabay relative to repo root)",
    )
    args = parser.parse_args(argv)

    if not args.api_key:
        print(
            "Error: no Pixabay API key provided. Pass --api-key or set PIXABAY_API_KEY.",
            file=sys.stderr,
        )
        return 2

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    per_category = args.count_per_category

    repo_root = Path(__file__).resolve().parent.parent
    output_dir = (
        Path(args.output_dir) if args.output_dir else repo_root / "images" / OUTPUT_DIR_NAME
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    total_planned = len(categories) * per_category
    print(
        f"Fetching {per_category} photos per category across {len(categories)} "
        f"categories ({total_planned} total) ..."
    )

    all_records: list[dict[str, str]] = []
    total_downloaded = 0

    for category in categories:
        print(f"\n=== Category: {category} ===")
        try:
            hits = fetch_hits(args.api_key, category, per_category)
        except RuntimeError as exc:
            print(f"  Error for category '{category}': {exc}")
            continue

        if not hits:
            print(f"  No results for '{category}'.")
            continue

        cat_downloaded = 0
        for idx, hit in enumerate(hits, start=1):
            image_url = hit.get("largeImageURL") or hit.get("webformatURL")
            if not image_url:
                print(f"  [{idx}/{len(hits)}] skip (no image URL): id={hit.get('id')}")
                continue

            pid = hit.get("id")
            author = hit.get("user", "unknown")
            tags = hit.get("tags", "")
            file_name = f"pixabay_{category}_{pid}_{slugify(tags or category)}.jpg"
            destination = output_dir / file_name

            try:
                raw = download_image_bytes(image_url)
                image = Image.open(io.BytesIO(raw))
                processed = resize_and_compress(image)
                destination.write_bytes(processed)
            except Exception as exc:  # noqa: BLE001 - any download/image error is skipped
                print(f"  [{idx}/{len(hits)}] failed id={pid}: {exc}")
                continue

            all_records.append(
                {
                    "category": category,
                    "file": file_name,
                    "id": str(pid),
                    "author": author,
                    "author_url": (f"https://pixabay.com/users/{author}-{hit.get('user_id')}/"),
                    "image_url": image_url,
                    "page_url": hit.get("pageURL", ""),
                    "tags": tags,
                }
            )
            cat_downloaded += 1
            total_downloaded += 1
            print(f"  [{idx}/{len(hits)}] ok -> {file_name}")
            time.sleep(REQUEST_DELAY_S)

        print(f"  Category '{category}': {cat_downloaded}/{len(hits)} downloaded.")

    write_credits(output_dir, all_records)
    print(f"\nDone: {total_downloaded} images downloaded.")
    print(f"Credits written to {output_dir / CREDITS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
