from __future__ import annotations

"""BBox-list helpers shared by page-cleaning code.

PyMuPDF ``Rect`` operations from step 01 are intentionally not generalized here;
they use different types and geometric semantics from the list-based helpers in
step 02.
"""

from typing import Any

BBox = list[float]


def item_bbox(item: dict[str, Any]) -> BBox:
    """Return a validated four-number bbox, or a zero bbox on invalid input."""
    raw = item.get("bbox", [0, 0, 0, 0])
    if not isinstance(raw, list) or len(raw) != 4:
        return [0.0, 0.0, 0.0, 0.0]

    try:
        return [float(value) for value in raw]
    except (TypeError, ValueError):
        return [0.0, 0.0, 0.0, 0.0]


def rounded_item_bbox(item: dict[str, Any], digits: int = 2) -> BBox:
    return [round(value, digits) for value in item_bbox(item)]


def union_bbox(first: BBox, second: BBox) -> BBox:
    return [
        min(first[0], second[0]),
        min(first[1], second[1]),
        max(first[2], second[2]),
        max(first[3], second[3]),
    ]


def horizontal_overlap_ratio(first: BBox, second: BBox) -> float:
    overlap = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    width = max(1.0, min(first[2] - first[0], second[2] - second[0]))
    return overlap / width


def vertical_overlap_ratio(first: BBox, second: BBox) -> float:
    overlap = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    height = max(1.0, min(first[3] - first[1], second[3] - second[1]))
    return overlap / height
