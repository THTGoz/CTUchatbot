from __future__ import annotations

import re
import unicodedata
from typing import Any


_SEMESTER_PATTERNS = (
    re.compile(r"(?:^|[^a-z0-9])hk\s*([123])(?:[^0-9]|$)", re.IGNORECASE),
    re.compile(r"học\s*kỳ\s*([123])", re.IGNORECASE),
)
_FULL_SCHOOL_YEAR = re.compile(r"(?<!\d)(20\d{2})\D+(20\d{2})(?!\d)")
_SHORT_SCHOOL_YEAR = re.compile(r"(?<!\d)(\d{2})[_-](\d{2})(?!\d)")


def _ascii_text(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value).casefold()).replace("đ", "d")
    return "".join(character for character in text if not unicodedata.combining(character))


def _first_non_empty(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def detect_notice_type(title: str) -> str:
    """Phân loại ở mức rộng, chỉ dựa trên tiêu đề của thông báo."""
    text = _ascii_text(title)
    if re.search(r"\bnganh\b", text) or (
        "chuyen" in text and "chuong trinh" in text
    ):
        return "xet_chuyen_nganh"
    if "diem ren luyen" in text:
        return "diem_ren_luyen"
    if "dang ky hoc phan" in text:
        return "dang_ky_hoc_phan"
    if "xoa" in text and "lop hoc phan" in text:
        return "xoa_lop_hoc_phan"
    if any(
        keyword in text
        for keyword in ("tet", "gio to", "quoc khanh")
    ):
        return "lich_nghi"
    return "thong_bao_khac"


def extract_semester(*values: object) -> int | None:
    text = " ".join(str(value or "") for value in values)
    for pattern in _SEMESTER_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    return None


def extract_school_year(*values: object) -> tuple[int, int] | None:
    text = " ".join(str(value or "") for value in values)
    match = _FULL_SCHOOL_YEAR.search(text)
    if match:
        return int(match.group(1)), int(match.group(2))

    match = _SHORT_SCHOOL_YEAR.search(text)
    if match:
        return 2000 + int(match.group(1)), 2000 + int(match.group(2))
    return None


def build_notice_metadata(
    *,
    filename: str,
    title: str,
    issue_date: str,
    source_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Tạo metadata chỉ dành cho node gốc ThongBao."""
    result: dict[str, Any] = {
        "loai_thong_bao": detect_notice_type(title),
    }
    if issue_date:
        result["ngay_ban_hanh"] = issue_date
        issue_year = re.search(r"(?<!\d)(20\d{2})(?!\d)", issue_date)
        if issue_year:
            result["nam_ban_hanh"] = int(issue_year.group(1))

    document_code = _first_non_empty(
        source_metadata.get("ma_van_ban"),
        source_metadata.get("so_van_ban"),
    )
    if document_code:
        result["ma_van_ban"] = document_code

    semester = extract_semester(filename, title)
    if semester is not None:
        result["hoc_ky"] = semester

    school_year = extract_school_year(filename, title)
    if school_year is not None:
        start_year, end_year = school_year
        result.update({
            "nam_hoc": f"{start_year}-{end_year}",
            "nam_hoc_bat_dau": start_year,
            "nam_hoc_ket_thuc": end_year,
        })

    return result
