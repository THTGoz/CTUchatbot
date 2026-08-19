from __future__ import annotations

"""Read-only traversal helpers for page-based intermediate JSON documents."""

from collections.abc import Iterator
from typing import Any


def iter_pages(document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield dictionary pages from ``document['trang']`` in stored order."""
    pages = document.get("trang", [])
    if not isinstance(pages, list):
        return

    for page in pages:
        if isinstance(page, dict):
            yield page


def page_items(page: dict[str, Any]) -> list[dict[str, Any]]:
    """Return dictionary items from one page without mutating the source."""
    items = page.get("items", [])
    if not isinstance(items, list):
        return []

    return [item for item in items if isinstance(item, dict)]


def iter_items(document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield all dictionary items from all valid pages."""
    for page in iter_pages(document):
        yield from page_items(page)


def iter_text_items(document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield items whose ``loai`` is ``van_ban``."""
    for item in iter_items(document):
        if item.get("loai") == "van_ban":
            yield item
