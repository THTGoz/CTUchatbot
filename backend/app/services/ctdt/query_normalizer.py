"""Chuẩn hóa deterministic riêng cho truy vấn CTĐT trước analyzer/retrieval."""

from __future__ import annotations

import re
from typing import Any


ABBREVIATIONS: dict[str, str] = {
    "khmt": "khoa học máy tính",
    "cntt": "công nghệ thông tin",
    "ctđt": "chương trình đào tạo",
    "ctdt": "chương trình đào tạo",
    "lvtn": "luận văn tốt nghiệp",
    "hk1": "học kỳ 1",
    "hk2": "học kỳ 2",
    "hk3": "học kỳ 3",
    "hk": "học kỳ",
    "hp": "học phần",
    "sv": "sinh viên",
    "tc": "tín chỉ",
}

SYNONYMS: dict[str, str] = {
    "chương trình học": "chương trình đào tạo",
    "môn học": "học phần",
    "đăng kí": "đăng ký",
    "học kì": "học kỳ",
}

KNOWN_TYPOS: dict[str, str] = {
    "đăn ký": "đăng ký",
    "chươn trình": "chương trình",
    "tín chị": "tín chỉ",
}


def _replace_dictionary(
    text: str,
    mapping: dict[str, str],
    rule_type: str,
    applied_rules: list[dict[str, str]],
) -> str:
    current = text
    for source in sorted(mapping, key=len, reverse=True):
        target = mapping[source]
        pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)

        def repl(match: re.Match[str]) -> str:
            matched = match.group(0)
            applied_rules.append({
                "type": rule_type,
                "source": matched,
                "target": target,
            })
            return target

        current = pattern.sub(repl, current)
    return current


def normalize_ctdt_query(query: str | None) -> dict[str, Any]:
    """Chuẩn hóa viết tắt/từ đồng nghĩa nhưng không thay đổi mã học phần."""
    original = "" if query is None else str(query)
    text = re.sub(r"\s+", " ", original).strip()
    applied_rules: list[dict[str, str]] = []

    if not text:
        return {
            "original_query": original,
            "normalized_query": "",
            "applied_rules": [],
        }

    text = _replace_dictionary(text, ABBREVIATIONS, "abbreviation", applied_rules)
    text = _replace_dictionary(text, SYNONYMS, "synonym", applied_rules)
    text = _replace_dictionary(text, KNOWN_TYPOS, "typo", applied_rules)
    text = re.sub(r"\s+", " ", text).strip()

    return {
        "original_query": original,
        "normalized_query": text,
        "applied_rules": applied_rules,
    }
