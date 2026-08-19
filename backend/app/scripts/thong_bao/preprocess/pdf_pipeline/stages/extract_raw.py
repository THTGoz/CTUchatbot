from __future__ import annotations

"""
BƯỚC 01 — TRÍCH XUẤT PDF THÔ

- Đọc toàn bộ PDF trong input/.
- Trích xuất văn bản và bảng theo thứ tự xuất hiện.
- Loại nội dung bảng khỏi các block văn bản để tránh trùng lặp.
- Ghi JSON vào output/01_raw_blocks/.

Chạy riêng bước này từ thư mục ``backend``:
    python -m app.scripts.thong_bao.preprocess.pdf_pipeline.stages.extract_raw
"""

import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pymupdf

from ..core.utils.io import save_json


# -----------------------------------------------------------------------------
# CẤU HÌNH
# -----------------------------------------------------------------------------

SCRIPT_VERSION = "3.2-refactor-io"

ROOT_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT_DIR / "input"
OUTPUT_DIR = ROOT_DIR / "output" / "01_raw_blocks"

TABLE_PADDING = 1.0
WORD_TABLE_OVERLAP_THRESHOLD = 0.20
LINE_SEPARATOR = "\n"
JSON_INDENT = 2


# -----------------------------------------------------------------------------
# KIỂU DỮ LIỆU NỘI BỘ
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class WordToken:
    text: str
    rect: pymupdf.Rect
    block_no: int
    line_no: int
    word_no: int


@dataclass
class TextLine:
    block_no: int
    line_no: int
    text: str
    rect: pymupdf.Rect


# -----------------------------------------------------------------------------
# HÌNH HỌC PYMuPDF
# -----------------------------------------------------------------------------

# Các helper này cố ý được giữ cục bộ. utils.bbox dùng list[float], trong khi
# bước 01 cần đúng ngữ nghĩa của pymupdf.Rect.

def rounded_bbox(rect: pymupdf.Rect) -> list[float]:
    return [round(float(value), 2) for value in (rect.x0, rect.y0, rect.x1, rect.y1)]


def expand_rect(rect: pymupdf.Rect, padding: float = TABLE_PADDING) -> pymupdf.Rect:
    return pymupdf.Rect(
        rect.x0 - padding,
        rect.y0 - padding,
        rect.x1 + padding,
        rect.y1 + padding,
    )


def intersection_ratio(subject: pymupdf.Rect, container: pymupdf.Rect) -> float:
    if subject.is_empty or subject.is_infinite or subject.get_area() <= 0:
        return 0.0

    intersection = subject & container
    if intersection.is_empty:
        return 0.0

    return float(intersection.get_area() / subject.get_area())


def union_rectangles(rectangles: Iterable[pymupdf.Rect]) -> pymupdf.Rect:
    iterator = iter(rectangles)
    try:
        result = pymupdf.Rect(next(iterator))
    except StopIteration as exc:
        raise ValueError("Không thể tạo bbox từ danh sách rỗng.") from exc

    for rect in iterator:
        result.include_rect(rect)
    return result


def overlaps_table(word_rect: pymupdf.Rect, table_rectangles: list[pymupdf.Rect]) -> bool:
    center = pymupdf.Point(
        (word_rect.x0 + word_rect.x1) / 2,
        (word_rect.y0 + word_rect.y1) / 2,
    )

    for table_rect in table_rectangles:
        expanded = expand_rect(table_rect)
        if expanded.contains(center):
            return True
        if intersection_ratio(word_rect, expanded) >= WORD_TABLE_OVERLAP_THRESHOLD:
            return True

    return False


# -----------------------------------------------------------------------------
# BẢNG
# -----------------------------------------------------------------------------

def normalize_table(rows: Any) -> list[list[str | None]]:
    if not rows:
        return []

    return [
        [None if cell is None else str(cell).strip() for cell in row]
        for row in rows
        if row is not None
    ]


def extract_tables(
    page: pymupdf.Page,
) -> tuple[list[dict[str, Any]], list[pymupdf.Rect]]:
    try:
        tables = page.find_tables().tables
    except Exception as exc:
        print(f"  [CẢNH BÁO] Trang {page.number + 1}: không thể phát hiện bảng ({exc}).")
        return [], []

    items: list[dict[str, Any]] = []
    rectangles: list[pymupdf.Rect] = []

    for table in tables:
        rect = pymupdf.Rect(table.bbox)
        rectangles.append(rect)

        try:
            rows = normalize_table(table.extract())
        except Exception as exc:
            print(f"  [CẢNH BÁO] Trang {page.number + 1}: không thể đọc một bảng ({exc}).")
            rows = []

        items.append({
            "loai": "bang",
            "bbox": rounded_bbox(rect),
            "du_lieu": rows,
        })

    return items, rectangles


# -----------------------------------------------------------------------------
# VĂN BẢN
# -----------------------------------------------------------------------------

def extract_words(page: pymupdf.Page) -> list[WordToken]:
    words: list[WordToken] = []

    for raw_word in page.get_text("words", sort=True):
        if len(raw_word) < 8:
            continue

        x0, y0, x1, y1, text, block_no, line_no, word_no = raw_word[:8]
        text = str(text).strip()
        rect = pymupdf.Rect(float(x0), float(y0), float(x1), float(y1))

        if not text or rect.is_empty or rect.is_infinite:
            continue

        words.append(WordToken(
            text=text,
            rect=rect,
            block_no=int(block_no),
            line_no=int(line_no),
            word_no=int(word_no),
        ))

    return words


def group_words_by_line(
    words: list[WordToken],
) -> dict[tuple[int, int], list[WordToken]]:
    grouped: dict[tuple[int, int], list[WordToken]] = defaultdict(list)
    for word in words:
        grouped[(word.block_no, word.line_no)].append(word)
    return grouped


def build_text_lines(words: list[WordToken]) -> dict[int, list[TextLine]]:
    lines_by_block: dict[int, list[TextLine]] = defaultdict(list)

    for (block_no, line_no), line_words in group_words_by_line(words).items():
        line_words.sort(key=lambda word: (word.word_no, word.rect.x0))
        text = " ".join(word.text for word in line_words).strip()
        if not text:
            continue

        lines_by_block[block_no].append(TextLine(
            block_no=block_no,
            line_no=line_no,
            text=text,
            rect=union_rectangles(word.rect for word in line_words),
        ))

    return lines_by_block


def build_text_items(words: list[WordToken]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    lines_by_block = build_text_lines(words)

    for block_no in sorted(lines_by_block):
        lines = sorted(
            lines_by_block[block_no],
            key=lambda line: (line.line_no, line.rect.y0, line.rect.x0),
        )
        text = LINE_SEPARATOR.join(line.text for line in lines).strip()
        if not text:
            continue

        items.append({
            "loai": "van_ban",
            "bbox": rounded_bbox(union_rectangles(line.rect for line in lines)),
            "noi_dung": text,
        })

    return items


def remove_text_inside_tables(
    text_items: list[dict[str, Any]],
    table_rectangles: list[pymupdf.Rect],
) -> list[dict[str, Any]]:
    """Lớp bảo vệ cuối cho các PDF có bbox bất thường."""
    if not table_rectangles:
        return text_items

    retained: list[dict[str, Any]] = []

    for item in text_items:
        rect = pymupdf.Rect(item["bbox"])
        center = pymupdf.Point(
            (rect.x0 + rect.x1) / 2,
            (rect.y0 + rect.y1) / 2,
        )

        fully_inside = any(
            expanded.contains(center) and intersection_ratio(rect, expanded) >= 0.90
            for expanded in (expand_rect(table_rect) for table_rect in table_rectangles)
        )

        if not fully_inside:
            retained.append(item)

    return retained


# -----------------------------------------------------------------------------
# TRANG VÀ PDF
# -----------------------------------------------------------------------------

def reading_order(item: dict[str, Any]) -> tuple[float, float, int]:
    x0, y0 = map(float, item.get("bbox", [0, 0])[:2])
    priority = 0 if item.get("loai") == "van_ban" else 1
    return y0, x0, priority


def extract_page(page: pymupdf.Page) -> tuple[dict[str, Any], dict[str, int]]:
    table_items, table_rectangles = extract_tables(page)
    all_words = extract_words(page)

    retained_words = [
        word for word in all_words
        if not overlaps_table(word.rect, table_rectangles)
    ]

    text_items = remove_text_inside_tables(
        build_text_items(retained_words),
        table_rectangles,
    )

    items = text_items + table_items
    items.sort(key=reading_order)

    page_data = {
        "so_trang": page.number + 1,
        "kich_thuoc": [
            round(float(page.rect.width), 2),
            round(float(page.rect.height), 2),
        ],
        "items": items,
    }

    stats = {
        "total_words": len(all_words),
        "removed_words": len(all_words) - len(retained_words),
        "retained_words": len(retained_words),
        "text_blocks": len(text_items),
        "tables": len(table_items),
    }
    return page_data, stats


def extract_pdf(pdf_path: Path) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []

    with pymupdf.open(pdf_path) as document:
        for page in document:
            page_data, stats = extract_page(page)
            pages.append(page_data)

            print(
                f"  Trang {page.number + 1}: "
                f"{stats['total_words']} từ, "
                f"loại {stats['removed_words']} từ trong bảng, "
                f"giữ {stats['retained_words']} từ, "
                f"{stats['text_blocks']} block text, "
                f"{stats['tables']} bảng"
            )

    return {"ten_file": pdf_path.name, "trang": pages}


# -----------------------------------------------------------------------------
# FILE VÀ MAIN
# -----------------------------------------------------------------------------

def find_input_pdfs() -> list[Path]:
    if not INPUT_DIR.exists():
        raise FileNotFoundError(f"Không tìm thấy thư mục input: {INPUT_DIR}")

    return sorted(
        path for path in INPUT_DIR.iterdir()
        if path.is_file() and path.suffix.lower() == ".pdf"
    )


def process_pdf(pdf_path: Path) -> bool:
    output_path = OUTPUT_DIR / f"{pdf_path.stem}_raw.json"
    print(f"\n[ĐANG XỬ LÝ] {pdf_path.name}")

    try:
        data = extract_pdf(pdf_path)
        save_json(
            data,
            output_path,
            indent=JSON_INDENT,
            ensure_ascii=False,
        )
    except Exception as exc:
        print(f"[LỖI] {pdf_path.name}: {exc}")
        return False

    print(f"[OK] {output_path}")
    return True


def main() -> int:
    print("=" * 72)
    print(f"extract_raw.py — phiên bản {SCRIPT_VERSION}")
    print(f"Input : {INPUT_DIR}")
    print(f"Output: {OUTPUT_DIR}")
    print("=" * 72)

    try:
        pdf_files = find_input_pdfs()
    except FileNotFoundError as exc:
        print(f"[LỖI] {exc}")
        return 1

    if not pdf_files:
        print(f"[LỖI] Không có file PDF trong: {INPUT_DIR}")
        return 1

    success_count = sum(process_pdf(pdf_path) for pdf_path in pdf_files)
    failed_count = len(pdf_files) - success_count

    print("\n" + "=" * 72)
    print(f"Hoàn tất: {success_count}/{len(pdf_files)} file thành công.")
    if failed_count:
        print(f"Có {failed_count} file xử lý thất bại.")
    print("=" * 72)

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
