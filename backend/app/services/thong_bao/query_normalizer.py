"""Chuẩn hóa deterministic riêng cho truy vấn thông báo, kế hoạch."""

from __future__ import annotations

import re
from typing import Any


# Các viết tắt có ý nghĩa định danh/ngữ nghĩa quan trọng được giữ cả alias gốc
# theo dạng "<cụm đầy đủ> (<ALIAS>)", giống cơ chế QueryNormalizer cũ của Linh.
ABBREVIATIONS: dict[str, str] = {
    "khht": "kế hoạch học tập",
    "dkhp": "đăng ký học phần",
    "đkhp": "đăng ký học phần",
    "ctđt": "chương trình đào tạo",
    "ctdt": "chương trình đào tạo",
    "khmt": "khoa học máy tính",
    "cntt": "công nghệ thông tin",
    "lvtn": "luận văn tốt nghiệp",
    "mssv": "mã số sinh viên",
    "hk1": "học kỳ 1",
    "hk2": "học kỳ 2",
    "hk3": "học kỳ 3",
    "hk": "học kỳ",
    "hp": "học phần",
    "sv": "sinh viên",
    "tc": "tín chỉ",
}

KEEP_ORIGINAL_ABBREVS: frozenset[str] = frozenset({
    "khht",
    "dkhp", "đkhp",
    "ctđt", "ctdt",
    "khmt",
    "cntt",
    "lvtn",
    "mssv",
})

SYNONYMS: dict[str, str] = {
    "đăng kí": "đăng ký",
    "học kì": "học kỳ",
    "môn học": "học phần",
    "mã sv": "mã sinh viên",
    "mã số sv": "mã số sinh viên",
    "khoá": "khóa",
}

KNOWN_TYPOS: dict[str, str] = {
    "đăn ký": "đăng ký",
    "đăng ky": "đăng ký",
    "học ki": "học kỳ",
    "sinh vien": "sinh viên",
    "hoc phan": "học phần",
}


# Bảo vệ các giá trị exact/temporal trước mọi phép thay thế.
# Thứ tự pattern quan trọng: mẫu cụ thể hơn đặt trước mẫu tổng quát hơn.
PROTECTED_PATTERN = re.compile(
    r"""
    (?:
        \b\d{4}-\d{1,2}-\d{1,2}\b                              # ISO date
      | \b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b                    # dd/mm/yyyy
      | \b\d{4}\s*[-–—/]\s*\d{4}\b                           # năm học
      | \b\d{7}_\d{2}_(?:STD|CLC)\b                           # mã CTĐT
      | \b[A-Z]{2,4}\d{3}[A-Z0-9]*\b                          # mã học phần
      | \b[A-Z]\d{7}\b                                        # MSSV
      | \bK\d{2}\b                                            # khóa K48...
      | \b\d{1,4}/[A-ZĐ][A-Z0-9Đ._-]*(?:-[A-ZĐ0-9._-]+)*\b   # mã văn bản cơ bản
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


class NotificationQueryNormalizer:
    """Bộ chuẩn hóa truy vấn thông báo bằng luật Python, không gọi LLM."""

    def __init__(self) -> None:
        self.abbreviations = ABBREVIATIONS
        self.synonyms = SYNONYMS
        self.known_typos = KNOWN_TYPOS

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"[\r\n\t]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _protect_values(text: str) -> tuple[str, dict[str, str]]:
        protected: dict[str, str] = {}

        def replace(match: re.Match[str]) -> str:
            token = f"ZZPROTECTEDTOKEN{len(protected)}ZZ"
            protected[token] = match.group(0)
            return token

        return PROTECTED_PATTERN.sub(replace, text), protected

    @staticmethod
    def _restore_values(text: str, protected: dict[str, str]) -> str:
        for token, original in protected.items():
            text = text.replace(token, original)
        return text

    @staticmethod
    def _build_rule_pattern(key: str, keep_original: bool) -> re.Pattern[str]:
        escaped = re.escape(key)
        if keep_original:
            # Không expand lại alias nếu nó đã nằm trong dạng "(KHHT)".
            return re.compile(
                rf"(?<!\()(?<!\w){escaped}(?!\w)(?!\s*\()",
                re.IGNORECASE,
            )
        return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)

    def _apply_dictionary(
        self,
        text: str,
        rules: dict[str, str],
        rule_type: str,
        applied_rules: list[dict[str, str]],
    ) -> str:
        current = text
        for key in sorted(rules, key=len, reverse=True):
            target = rules[key]
            keep_original = key in KEEP_ORIGINAL_ABBREVS
            replacement = f"{target} ({key.upper()})" if keep_original else target
            pattern = self._build_rule_pattern(key, keep_original)

            def repl(match: re.Match[str]) -> str:
                source = match.group(0)
                if source.casefold() != replacement.casefold():
                    applied_rules.append({
                        "type": rule_type,
                        "source": source,
                        "target": replacement,
                    })
                return replacement

            current = pattern.sub(repl, current)
        return current

    def normalize(self, query: str | None) -> dict[str, Any]:
        raw_query = "" if query is None else str(query)
        applied_rules: list[dict[str, str]] = []

        text = self._normalize_whitespace(raw_query)
        if not text:
            return {
                "original_query": raw_query,
                "normalized_query": "",
                "applied_rules": [],
            }

        text, protected = self._protect_values(text)
        text = self._apply_dictionary(
            text, self.abbreviations, "abbreviation", applied_rules
        )
        text = self._apply_dictionary(
            text, self.synonyms, "synonym", applied_rules
        )
        text = self._apply_dictionary(
            text, self.known_typos, "typo", applied_rules
        )
        text = self._restore_values(text, protected)

        return {
            "original_query": raw_query,
            "normalized_query": self._normalize_whitespace(text),
            "applied_rules": applied_rules,
        }


notification_query_normalizer = NotificationQueryNormalizer()


def normalize_notification_query(query: str | None) -> dict[str, Any]:
    """Convenience function dùng chung trong pipeline/test."""
    return notification_query_normalizer.normalize(query)
