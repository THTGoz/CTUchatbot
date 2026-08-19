from __future__ import annotations

"""Chạy lại năm loại Thông báo và so sánh với JSON chuẩn.

Môi trường chỉ cần thư viện chuẩn khi bắt đầu từ JSON thô (bước 02). Muốn
kiểm tra cả bước đọc PDF, cài dependency trong ``requirements.txt`` rồi chạy
``chay_mot_pdf`` cho file tương ứng.
"""

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .pipeline import ROOT_DIR, configure_utf8_console, run_single_input


GOLDEN_DIR = ROOT_DIR / "tests" / "golden"
RAW_DIR = ROOT_DIR / "output" / "01_raw_blocks"


@dataclass(frozen=True)
class GoldenFixture:
    """Liên kết một loại thông báo với JSON thô và JSON cuối đã duyệt."""

    notice_type: str
    raw_filename: str
    golden_filename: str


GOLDEN_FIXTURES: tuple[GoldenFixture, ...] = (
    GoldenFixture(
        "dang_ky_hoc_phan",
        "KHGDVDKHP_HK1_26_27_raw.json",
        "dang_ky_hoc_phan.json",
    ),
    GoldenFixture(
        "diem_ren_luyen",
        "DRL_HK1_2025_2026_raw.json",
        "diem_ren_luyen.json",
    ),
    GoldenFixture("lich_nghi", "Tet2026_raw.json", "lich_nghi.json"),
    GoldenFixture(
        "chuyen_nganh",
        "ChuyenNganh10_2025.signed.signed_raw.json",
        "chuyen_nganh.json",
    ),
    GoldenFixture(
        "xoa_lop_hoc_phan",
        "Xoalop_HK2_2025_2026_raw.json",
        "xoa_lop_hoc_phan.json",
    ),
)


def load_json(path: Path) -> Any:
    """Đọc JSON UTF-8 phục vụ so sánh theo dữ liệu, không theo khoảng trắng."""
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def sha256(path: Path) -> str:
    """Tính checksum để báo cả trường hợp nội dung byte giống tuyệt đối."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(64 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def first_difference(expected: Any, actual: Any, path: str = "$") -> str | None:
    """Trả về vị trí khác đầu tiên để lỗi golden master dễ điều tra."""
    if type(expected) is not type(actual):
        return f"{path}: khác kiểu {type(expected).__name__} != {type(actual).__name__}"

    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            missing = sorted(expected.keys() - actual.keys())
            extra = sorted(actual.keys() - expected.keys())
            return f"{path}: thiếu key={missing}, thừa key={extra}"
        for key in expected:
            difference = first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
        return None

    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}: khác số phần tử {len(expected)} != {len(actual)}"
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            difference = first_difference(
                expected_item,
                actual_item,
                f"{path}[{index}]",
            )
            if difference:
                return difference
        return None

    if expected != actual:
        return f"{path}: {expected!r} != {actual!r}"
    return None


def verify_fixture(fixture: GoldenFixture, temporary_root: Path) -> tuple[bool, str]:
    """Chạy bước 02–06 cho một mẫu và trả kết quả so sánh dễ đọc."""
    raw_path = RAW_DIR / fixture.raw_filename
    golden_path = GOLDEN_DIR / fixture.golden_filename
    if not raw_path.is_file() or not golden_path.is_file():
        return False, f"thiếu fixture: raw={raw_path.is_file()}, golden={golden_path.is_file()}"

    actual_path = run_single_input(
        raw_path,
        temporary_root / fixture.notice_type,
        from_step=2,
        to_step=6,
    )
    expected_data = load_json(golden_path)
    actual_data = load_json(actual_path)
    difference = first_difference(expected_data, actual_data)
    if difference:
        return False, difference

    byte_status = "byte-identical" if sha256(golden_path) == sha256(actual_path) else "JSON-identical"
    return True, f"{byte_status}, sha256={sha256(actual_path)}"


def main() -> int:
    """Xác minh cả năm loại và trả mã lỗi nếu có một loại bị thay đổi."""
    configure_utf8_console()
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="notification_pdf_golden_") as directory:
        temporary_root = Path(directory)
        for fixture in GOLDEN_FIXTURES:
            passed, details = verify_fixture(fixture, temporary_root)
            status = "PASS" if passed else "FAIL"
            print(f"[{status}] {fixture.notice_type}: {details}")
            if not passed:
                failures.append(fixture.notice_type)

    print(f"\nKết quả: {len(GOLDEN_FIXTURES) - len(failures)}/{len(GOLDEN_FIXTURES)} loại khớp golden master.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
