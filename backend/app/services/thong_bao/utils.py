"""Small normalization helpers required by notification retrieval."""

from __future__ import annotations

import unicodedata


def bo_dau(value: object) -> str:
    """Chuẩn hóa một giá trị về chữ thường không dấu để so khớp ổn định."""
    normalized = unicodedata.normalize("NFD", str(value).casefold()).replace("đ", "d")
    return "".join(character for character in normalized if not unicodedata.combining(character))
