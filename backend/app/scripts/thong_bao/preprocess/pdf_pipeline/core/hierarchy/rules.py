from __future__ import annotations

import re
from typing import Any

from ..utils.text import normalize_unicode


DOCUMENT_TYPE_WORDS = {
    "THÔNG BÁO",
    "QUYẾT ĐỊNH",
    "QUY ĐỊNH",
    "KẾ HOẠCH",
    "HƯỚNG DẪN",
    "BÁO CÁO",
    "CÔNG VĂN",
    "CHỈ THỊ",
    "NGHỊ QUYẾT",
    "TỜ TRÌNH",
    "BIÊN BẢN",
    "DANH SÁCH",
    "PHỤ LỤC",
    "LỊCH THI",
    "LỊCH HỌC",
}

HIERARCHICAL_SECTION_RE = re.compile(
    r"^\s*(?P<number>\d+(?:\.\d+)+)\.?\s+(?P<title>.+)$",
    re.DOTALL,
)
LEVEL_ONE_SECTION_RE = re.compile(
    r"^\s*(?P<number>\d+)\.\s+(?P<title>.+)$",
    re.DOTALL,
)
ROMAN_SECTION_RE = re.compile(
    r"^\s*(?P<number>[IVXLCDM]+)\.\s+(?P<title>.+)$",
    re.IGNORECASE | re.DOTALL,
)
STEP_SECTION_RE = re.compile(
    r"^\s*BƯỚC\s+(?P<number>\d+)\s*[.：:\-–—]?\s*(?P<title>.*)$",
    re.IGNORECASE | re.DOTALL,
)
ARTICLE_SECTION_RE = re.compile(
    r"^\s*ĐIỀU\s+(?P<number>\d+[A-ZĐ]?)\s*[.)：:]?\s*(?P<title>.*)$",
    re.IGNORECASE | re.DOTALL,
)

SUBJECT_RE = re.compile(r"^\s*(?:V\s*/\s*v|Về\s+việc)\b", re.IGNORECASE)
ATTACHMENT_NOTE_RE = re.compile(r"^\s*\((?:Đính\s+kèm|Kèm\s+theo)\b", re.IGNORECASE)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = normalize_unicode(str(value))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_all_caps(text: str) -> bool:
    letters = [character for character in clean_text(text) if character.isalpha()]
    return bool(letters) and all(character.isupper() for character in letters)


def first_nonempty_line(text: str) -> str:
    for line in clean_text(text).splitlines():
        line = clean_text(line)
        if line:
            return line
    return ""


def starts_with_document_type(text: str) -> bool:
    first = first_nonempty_line(text)
    if not first:
        return False

    # Preserve case here. A body sentence such as "thông báo đến..." is not a
    # document boundary, while an official heading normally starts with the
    # uppercase type name.
    return any(first == word or first.startswith(f"{word} ") for word in DOCUMENT_TYPE_WORDS)


def comparison_key(text: str) -> str:
    value = clean_text(text).casefold()
    value = re.sub(r"[^\wÀ-ỹĐđ]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def titles_overlap(first: str, second: str) -> bool:
    left = comparison_key(first)
    right = comparison_key(second)
    return bool(left and right and (left == right or left in right or right in left))


def looks_like_document_start(text: str, kind: str = "") -> bool:
    value = clean_text(text)
    if not value:
        return False

    kind = clean_text(kind).casefold()
    first = first_nonempty_line(value)

    if starts_with_document_type(value):
        return kind in {"tieu_de", "heading", ""} or is_all_caps(first)

    # A title item beginning with “Về việc” can mark a new embedded document
    # when the explicit type line was merged or omitted by the PDF layout.
    if kind == "tieu_de" and SUBJECT_RE.match(first):
        return True

    return False


def looks_like_table_document_start(title: str) -> bool:
    value = clean_text(title)
    return bool(value and starts_with_document_type(value))


def parse_section(text: str) -> tuple[str, int] | None:
    value = clean_text(text)
    if not value:
        return None

    match = HIERARCHICAL_SECTION_RE.match(value)
    if match:
        number = match.group("number")
        return number, number.count(".") + 1

    match = LEVEL_ONE_SECTION_RE.match(value)
    if match:
        return match.group("number"), 1

    match = ROMAN_SECTION_RE.match(value)
    if match:
        return match.group("number").upper(), 1

    match = STEP_SECTION_RE.match(value)
    if match:
        return f"Bước {match.group('number')}", 1

    match = ARTICLE_SECTION_RE.match(value)
    if match:
        return f"Điều {match.group('number')}", 1

    return None
