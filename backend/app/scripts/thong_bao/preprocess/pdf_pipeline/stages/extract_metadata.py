"""
extract_metadata.py
======================

Phiên bản 3.0

Mục tiêu
--------
Trích metadata từ JSON đã làm sạch ở bước 02 và bổ sung các thống kê cơ bản
phục vụ bước xây dựng tài liệu cuối cùng.

Đầu vào
-------
output/02_clean/*_clean.json

Đầu ra
------
output/03_metadata/*_metadata.json

Cấu trúc đầu ra
---------------
{
  "ten_file": "...pdf",
  "ma_van_ban": "157/TB-ĐHCT",
  "ngay_ban_hanh": "2026-01-14",
  "tieu_de": "Về việc ...",
  "so_trang": 8,
  "trang": [...]
}

Không lưu
---------
- nam_ban_hanh
- loai_van_ban
- so_van_ban
- ky_hieu
- so_bang

"nam_ban_hanh" có thể suy ra từ ngay_ban_hanh khi cần.
"so_van_ban" và "ky_hieu" có thể suy ra từ ma_van_ban khi cần.

"so_bang" chưa được tính ở bước này vì một bảng logic có thể bị tách thành
nhiều block ở nhiều trang. Bước 4 sẽ hợp nhất bảng liên trang rồi mới tính
số bảng logic chính xác.

Nguyên tắc
----------
- Không sửa nội dung đã clean.
- Không ghép hoặc chia lại item.
- Xóa item có "dang": "metadata" khỏi từng trang vì mã văn bản và ngày
  ban hành đã được đưa lên metadata cấp tài liệu.
- Không tạo dữ liệu giả khi không trích được metadata.\n- Ngày ban hành chỉ lấy từ vùng metadata đầu văn bản; không quét phần căn cứ.\n- Hỗ trợ độ chính xác ngày ở ba mức: YYYY-MM-DD, YYYY-MM và YYYY.
- Không dùng argparse.
"""

from __future__ import annotations

import json
import re
import sys
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from ..core.utils.document import iter_pages, iter_text_items
from ..core.utils.text import normalize_unicode


SCRIPT_VERSION = "3.2-content-only-metadata"

ROOT_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT_DIR / "output" / "02_clean"
OUTPUT_DIR = ROOT_DIR / "output" / "03_metadata"
JSON_INDENT = 2


# =============================================================================
# Regex
# =============================================================================

DOCUMENT_CODE_REGEX = re.compile(
    r"\bSố\s*:?\s*"
    r"(?P<number>\d{1,6})"
    r"\s*/\s*"
    r"(?P<symbol>[A-ZÀ-ỸĐ0-9][A-ZÀ-ỸĐ0-9&.\-–—/]*)",
    re.IGNORECASE,
)

FULL_DATE_REGEX = re.compile(
    r"\bngày\s+(?P<day>\d{1,2})"
    r"\s+tháng\s+(?P<month>\d{1,2})"
    r"\s*năm\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)

MONTH_YEAR_REGEX = re.compile(
    r"\btháng\s+(?P<month>\d{1,2})"
    r"\s*năm\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)

PARTIAL_DATE_REGEX = re.compile(
    r"\bngày"
    r"(?:\s+(?P<day>\d{1,2}))?"
    r"\s+tháng"
    r"(?:\s+(?P<month>\d{1,2}))?"
    r"\s*năm\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)

ISSUE_DATE_CONTEXT_REGEX = re.compile(
    r"\bCần\s+Thơ\s*,?\s*ngày\b",
    re.IGNORECASE,
)

APPENDIX_REGEX = re.compile(
    r"^(?:PHỤ\s+LỤC|DANH\s+SÁCH)\b",
    re.IGNORECASE,
)


SUBJECT_REGEX = re.compile(
    r"^(?:V\s*/\s*v|Về\s+việc)\s*[:\-]?\s*(?P<title>.+)$",
    re.IGNORECASE,
)



# =============================================================================
# Dataclass
# =============================================================================

@dataclass
class Metadata:
    ten_file: str
    ma_van_ban: str
    ngay_ban_hanh: str | None
    tieu_de: str
    so_trang: int


# =============================================================================
# Chuẩn hóa
# =============================================================================

def normalize_space(text: str) -> str:
    text = normalize_unicode(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def normalize_symbol(symbol: str) -> str:
    symbol = normalize_space(symbol)
    symbol = symbol.replace("–", "-").replace("—", "-")
    symbol = re.sub(r"\s+", "", symbol)
    return symbol.upper().strip("/")


def normalize_document_code(number: str, symbol: str) -> str:
    number = number.strip()
    symbol = normalize_symbol(symbol)

    if not number or not symbol:
        return ""

    return f"{number}/{symbol}"


def split_lines(text: str) -> list[str]:
    result: list[str] = []

    for line in normalize_unicode(text).splitlines():
        line = normalize_space(line)
        if line:
            result.append(line)

    return result



# =============================================================================
# Duyệt tài liệu
# =============================================================================

def items_by_kind(
    document: dict[str, Any],
    kind: str,
) -> list[dict[str, Any]]:
    return [
        item
        for item in iter_text_items(document)
        if item.get("dang") == kind
    ]


def iter_metadata_items(
    document: dict[str, Any],
) -> Iterable[dict[str, Any]]:
    """
    Chỉ duyệt các item metadata, ưu tiên đúng vùng đầu văn bản.

    Không fallback sang toàn bộ nội dung vì ngày trong phần căn cứ,
    lịch trình hoặc phụ lục không phải ngày ban hành.
    """
    for page in iter_pages(document):
        items = page.get("items", [])

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("loai") != "van_ban":
                continue
            if item.get("dang") == "metadata":
                yield item


# =============================================================================
# Mã văn bản
# =============================================================================

def extract_document_code(
    document: dict[str, Any],
) -> str:
    """Trả về mã hiển thị trong vùng metadata, không quét phần viện dẫn."""
    for item in iter_metadata_items(document):

        text = normalize_space(str(item.get("noi_dung", "")))
        match = DOCUMENT_CODE_REGEX.search(text)

        if not match:
            continue

        number = match.group("number").strip()
        symbol = normalize_symbol(match.group("symbol"))
        code = normalize_document_code(number, symbol)

        return code

    return ""


# =============================================================================
# Ngày ban hành
# =============================================================================

def valid_date(year: int, month: int, day: int) -> bool:
    try:
        date(year, month, day)
        return True
    except ValueError:
        return False


def valid_month(month: int) -> bool:
    return 1 <= month <= 12


def extract_date_from_metadata_text(text: str) -> str | None:
    text = normalize_space(text)

    # Chỉ chấp nhận ngày nằm trong ngữ cảnh dòng ban hành chính thức.
    # Ví dụ: "Cần Thơ, ngày 12 tháng 3 năm 2026".
    if not ISSUE_DATE_CONTEXT_REGEX.search(text):
        return None

    full_match = FULL_DATE_REGEX.search(text)
    if full_match:
        day = int(full_match.group("day"))
        month = int(full_match.group("month"))
        year = int(full_match.group("year"))

        if valid_date(year, month, day):
            return f"{year:04d}-{month:02d}-{day:02d}"

        return None

    month_match = MONTH_YEAR_REGEX.search(text)
    if month_match:
        month = int(month_match.group("month"))
        year = int(month_match.group("year"))

        if valid_month(month):
            return f"{year:04d}-{month:02d}"

        return None

    partial_match = PARTIAL_DATE_REGEX.search(text)
    if partial_match:
        month_text = partial_match.group("month")
        year = int(partial_match.group("year"))

        # Khi thiếu ngày nhưng còn tháng và năm, giữ độ chính xác theo tháng.
        if month_text is not None:
            month = int(month_text)
            if valid_month(month):
                return f"{year:04d}-{month:02d}"
            return None

        # Nếu thiếu tháng thì không thể sử dụng riêng thành phần ngày.
        # Chỉ lưu năm để không tạo ra một ngày ban hành giả.
        return f"{year:04d}"

    return None


def extract_issue_date(
    document: dict[str, Any],
) -> str | None:
    """
    Trích ngày ban hành chỉ từ item metadata.

    Không quét phần căn cứ hoặc nội dung chính để tránh lấy nhầm ngày của
    thông tư, quyết định được viện dẫn hoặc thời hạn thực hiện.
    """
    for item in iter_metadata_items(document):
        text = str(item.get("noi_dung", ""))
        issue_date = extract_date_from_metadata_text(text)

        if issue_date:
            return issue_date

    return None


# =============================================================================
# Tiêu đề
# =============================================================================

def clean_title_line(line: str) -> str:
    line = normalize_space(line)
    match = SUBJECT_REGEX.match(line)

    if not match:
        return line

    title = match.group("title").strip()
    return f"Về việc {title}"


def title_from_subject_line(
    document: dict[str, Any],
) -> str:
    candidates = (
        items_by_kind(document, "metadata")
        + list(iter_text_items(document))
    )

    seen: set[int] = set()

    for item in candidates:
        object_id = id(item)

        if object_id in seen:
            continue

        seen.add(object_id)

        for line in split_lines(str(item.get("noi_dung", ""))):
            if SUBJECT_REGEX.match(line):
                return clean_title_line(line)

    return ""


def title_from_title_block(
    document: dict[str, Any],
) -> str:
    for item in items_by_kind(document, "tieu_de"):
        lines = split_lines(str(item.get("noi_dung", "")))

        if not lines:
            continue

        if APPENDIX_REGEX.search(lines[0]):
            continue

        content_lines: list[str] = []

        for line in lines:
            if normalize_space(line).upper() == "THÔNG BÁO":
                continue

            if line.startswith("("):
                continue

            content_lines.append(clean_title_line(line))

        if content_lines:
            return " ".join(content_lines)

    return ""


def title_from_filename(filename: str) -> str:
    """
    Chỉ dùng làm fallback cuối cùng.

    Tên file thường có mã kỹ thuật và hậu tố signed nên không dùng toàn bộ
    tên file làm tiêu đề.
    """
    stem = Path(filename).stem
    stem = re.sub(r"(?:\.signed)+$", "", stem, flags=re.I)
    stem = re.sub(r"_+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()

    if not stem:
        return ""

    match = re.search(
        r"(?:thông báo|về việc|v/v)\s+(.+)$",
        stem,
        flags=re.I,
    )

    if match:
        return f"Về việc {match.group(1).strip()}"

    return ""


def extract_title(document: dict[str, Any]) -> str:
    # Dòng V/v là trích yếu chính thức của công văn.
    title = title_from_subject_line(document)
    if title:
        return title

    title = title_from_title_block(document)
    if title:
        return title

    return title_from_filename(str(document.get("ten_file", "")))


# =============================================================================
# Thống kê tài liệu
# =============================================================================

def count_pages(document: dict[str, Any]) -> int:
    return sum(1 for _ in iter_pages(document))


# =============================================================================
# Trích metadata hoàn chỉnh
# =============================================================================

def extract_metadata(document: dict[str, Any]) -> Metadata:
    filename = str(document.get("ten_file", "")).strip()

    document_code = extract_document_code(document)
    issue_date = extract_issue_date(document)
    title = extract_title(document)

    return Metadata(
        ten_file=filename,
        ma_van_ban=document_code,
        ngay_ban_hanh=issue_date,
        tieu_de=title,
        so_trang=count_pages(document),
    )


def build_output(document: dict[str, Any]) -> dict[str, Any]:
    output = asdict(extract_metadata(document))
    pages = deepcopy(document.get("trang", []))

    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue

            items = page.get("items", [])
            if not isinstance(items, list):
                continue

            page["items"] = [
                item
                for item in items
                if not (
                    isinstance(item, dict)
                    and item.get("dang") == "metadata"
                )
            ]

    output["trang"] = pages
    return output


# =============================================================================
# Kiểm tra chất lượng
# =============================================================================

def metadata_warnings(metadata: Metadata) -> list[str]:
    warnings: list[str] = []

    if not metadata.ma_van_ban:
        warnings.append("không trích được mã văn bản")

    if metadata.ngay_ban_hanh is None:
        warnings.append("không trích được ngày ban hành")
    elif re.fullmatch(r"\d{4}", metadata.ngay_ban_hanh):
        warnings.append("ngày ban hành chỉ có năm")
    elif re.fullmatch(r"\d{4}-\d{2}", metadata.ngay_ban_hanh):
        warnings.append("ngày ban hành chỉ có tháng và năm")

    if not metadata.tieu_de:
        warnings.append("không trích được tiêu đề")

    if metadata.so_trang == 0:
        warnings.append("tài liệu không có trang")

    return warnings


# =============================================================================
# I/O
# =============================================================================

def output_name(input_path: Path) -> str:
    stem = re.sub(
        r"_clean(?:\(\d+\))?$",
        "",
        input_path.stem,
        flags=re.IGNORECASE,
    )

    return f"{stem}_metadata.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("JSON đầu vào phải là object.")

    return data


def save_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=JSON_INDENT,
        )


def find_input_files() -> list[Path]:
    if not INPUT_DIR.exists():
        return []

    return sorted(
        path
        for path in INPUT_DIR.glob("*.json")
        if path.is_file()
    )


def process_file(input_path: Path) -> bool:
    try:
        source = load_json(input_path)
        metadata = extract_metadata(source)
        output = build_output(source)

        destination = OUTPUT_DIR / output_name(input_path)
        save_json(output, destination)

        print(f"[OK] {input_path.name}")
        print(f"     Mã:       {metadata.ma_van_ban or '(trống)'}")
        print(f"     Ngày:     {metadata.ngay_ban_hanh or '(trống)'}")
        print(f"     Tiêu đề:  {metadata.tieu_de or '(trống)'}")
        print(f"     Số trang: {metadata.so_trang}")
        warnings = metadata_warnings(metadata)

        if warnings:
            print(f"     Cảnh báo: {'; '.join(warnings)}")

        print(f"     Đầu ra:   {destination}")
        return True

    except json.JSONDecodeError as error:
        print(
            f"[LỖI JSON] {input_path.name}: "
            f"dòng {error.lineno}, cột {error.colno}: {error.msg}"
        )
    except Exception as error:
        print(f"[LỖI] {input_path.name}: {error}")

    return False


def main() -> int:
    print(f"extract_metadata.py — phiên bản {SCRIPT_VERSION}")
    print(f"Đầu vào : {INPUT_DIR}")
    print(f"Đầu ra  : {OUTPUT_DIR}")
    print("-" * 76)

    files = find_input_files()

    if not files:
        print("Không tìm thấy file JSON đã clean.")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    success_count = sum(
        process_file(path)
        for path in files
    )

    print("-" * 76)
    print(
        f"Hoàn thành: {success_count}/{len(files)} file thành công."
    )

    return 0 if success_count == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
