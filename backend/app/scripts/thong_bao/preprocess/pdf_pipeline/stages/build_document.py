from __future__ import annotations

import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..core.utils.document import iter_pages, page_items
from ..core.utils.text import normalize_unicode as normalize_unicode_base

SCRIPT_VERSION = "1.3.2-resolve-roman-footnotes"

ROOT_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT_DIR / "output" / "03_metadata"
OUTPUT_DIR = ROOT_DIR / "output" / "04_document"
JSON_INDENT = 2

DOCUMENT_TYPE_LINES = {
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
}

APPENDIX_TITLE_REGEX = re.compile(
    r"\b(?:PHỤ LỤC|DANH SÁCH)\b",
    re.IGNORECASE,
)

PDF_SYMBOL_REPLACEMENTS = {
    "\uf0e0": " đến ",   # : mũi tên chỉ khoảng thời gian
    "\uf0b7": "-",       # bullet thường gặp trong font Symbol/Wingdings
}

def normalize_pdf_symbols(text: str) -> str:
    for source, target in PDF_SYMBOL_REPLACEMENTS.items():
        text = text.replace(source, target)

    return text

def normalize_numeric_ranges(text: str) -> str:
    return re.sub(
        r"(?<=\d)\s*đến\s*(?=\d)",
        " đến ",
        text,
        flags=re.IGNORECASE,
    )

def normalize_time_spacing(text: str) -> str:
    return re.sub(
        r"\b([01]?\d|2[0-3])\s*:\s*([0-5]\d)\b",
        r"\1:\2",
        text,
    )

def normalize_unicode(text: str) -> str:
    # Unicode cleanup is shared; PDF symbol mapping remains step-specific.
    return normalize_pdf_symbols(normalize_unicode_base(text))

def normalize_text(text: Any) -> str:
    if text is None:
        return ""

    value = normalize_unicode(str(text))
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = normalize_numeric_ranges(value)
    value = normalize_time_spacing(value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()

def normalize_cell(value: Any) -> str:
    text = normalize_text(value)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = normalize_numeric_ranges(text)
    text = normalize_time_spacing(text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()

def comparison_key(text: Any) -> str:
    value = normalize_cell(text).casefold()
    value = re.sub(r"[^\wÀ-ỹĐđ]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()

def normalized_title_for_compare(title: Any) -> str:
    return comparison_key(title)

def normalize_document_title_for_compare(title: Any) -> str:
    value = normalize_cell(title)
    value = re.sub(
        r"^\s*(?:v\s*/\s*v|về\s+việc|về)\s*[:\-–—]?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return comparison_key(value)

def title_lines(text: str) -> list[str]:
    return [
        normalize_text(line)
        for line in normalize_text(text).splitlines()
        if normalize_text(line)
    ]

def remove_type_line(text: str) -> str:
    lines = title_lines(text)

    kept = [
        line
        for line in lines
        if line.upper() not in DOCUMENT_TYPE_LINES
    ]

    return " ".join(kept).strip()

def is_main_document_title(
    item: dict[str, Any],
    document_title: str,
    page_number: int,
) -> bool:
    if item.get("loai") != "van_ban":
        return False

    if item.get("dang") != "tieu_de":
        return False

    if page_number != 1:
        return False

    text = normalize_text(item.get("noi_dung", ""))

    if not text:
        return True

    if APPENDIX_TITLE_REGEX.search(text):
        return False

    candidate = remove_type_line(text)

    if not candidate:
        return True

    candidate_key = normalize_document_title_for_compare(candidate)
    title_key = normalize_document_title_for_compare(document_title)

    if not title_key:
        return False

    return (
        candidate_key == title_key
        or candidate_key in title_key
        or title_key in candidate_key
    )

def build_text_item(item: dict[str, Any]) -> dict[str, Any] | None:
    content = normalize_text(item.get("noi_dung", ""))

    if not content:
        return None

    kind = normalize_text(item.get("dang", "")) or "doan_van"

    return {
        "loai": "van_ban",
        "dang": kind,
        "noi_dung": content,
    }

def normalize_row(row: Any) -> list[str]:
    if not isinstance(row, list):
        return []

    return [
        normalize_cell(cell)
        for cell in row
    ]

def make_unique_columns(columns: list[str]) -> list[str]:
    result: list[str] = []
    counts: dict[str, int] = {}

    for index, raw_column in enumerate(columns, start=1):
        column = raw_column.strip() or f"cot_{index}"

        count = counts.get(column, 0) + 1
        counts[column] = count

        if count > 1:
            column = f"{column}_{count}"

        result.append(column)

    return result

def pad_or_trim_row(row: list[str], width: int) -> list[str]:
    if width <= 0:
        return row

    if len(row) < width:
        return row + [""] * (width - len(row))

    if len(row) > width:
        return row[:width]

    return row

def build_table_item(item: dict[str, Any]) -> dict[str, Any] | None:
    raw_data = item.get("du_lieu", [])

    if not isinstance(raw_data, list):
        return None

    rows = [
        normalize_row(row)
        for row in raw_data
        if isinstance(row, list)
    ]

    rows = [
        row
        for row in rows
        if any(cell for cell in row)
    ]

    if not rows:
        return None

    columns = make_unique_columns(rows[0])
    width = len(columns)

    data_rows = [
        pad_or_trim_row(row, width)
        for row in rows[1:]
    ]

    return {
        "loai": "bang",
        "tieu_de_bang": normalize_text(
            item.get("tieu_de_bang", "")
        ),
        "cot": columns,
        "du_lieu": data_rows,
    }

def table_header_key(table: dict[str, Any]) -> tuple[str, ...]:
    columns = table.get("cot", [])

    if not isinstance(columns, list):
        return tuple()

    return tuple(
        comparison_key(column)
        for column in columns
    )

def tables_are_continuation(
    previous_table: dict[str, Any],
    current_table: dict[str, Any],
) -> bool:
    previous_header = table_header_key(previous_table)
    current_header = table_header_key(current_table)

    if not previous_header or not current_header:
        return False

    if previous_header != current_header:
        return False

    previous_title = normalized_title_for_compare(
        previous_table.get("tieu_de_bang", "")
    )
    current_title = normalized_title_for_compare(
        current_table.get("tieu_de_bang", "")
    )

    if previous_title and current_title and previous_title != current_title:
        return False

    return True

def merge_table_data(
    target: dict[str, Any],
    source: dict[str, Any],
) -> None:
    source_rows = source.get("du_lieu", [])

    if not isinstance(source_rows, list):
        return

    target.setdefault("du_lieu", []).extend(
        deepcopy(source_rows)
    )

def first_meaningful_item_index(
    items: list[dict[str, Any]],
    document_title: str,
    page_number: int,
) -> int | None:
    for index, item in enumerate(items):
        if item.get("loai") == "van_ban":
            if item.get("dang") == "metadata":
                continue

            if is_main_document_title(
                item,
                document_title,
                page_number,
            ):
                continue

            if not normalize_text(item.get("noi_dung", "")):
                continue

            return index

        if item.get("loai") == "bang":
            return index

    return None

TABLE_INTRO_SUFFIXES = (
    "như sau:",
    "cụ thể như sau:",
    "theo bảng sau:",
    "được thể hiện trong bảng sau:",
)

def strip_bullet_marker(text: Any) -> str:
    value = normalize_text(text)
    return re.sub(r"^\s*[-+•▪◦‣–—]\s*", "", value).strip()

def is_table_intro_paragraph(text: Any) -> bool:
    value = normalize_text(text).casefold()
    return any(value.endswith(suffix) for suffix in TABLE_INTRO_SUFFIXES)

def is_document_title_like(text: Any, document_title: str) -> bool:
    candidate = normalize_document_title_for_compare(text)
    title = normalize_document_title_for_compare(document_title)

    if not candidate or not title:
        return False

    return candidate == title or candidate in title or title in candidate

def infer_table_title(
    result: list[dict[str, Any]],
    document_title: str,
) -> str:
    for previous in reversed(result):
        if previous.get("loai") != "van_ban":
            break

        kind = normalize_text(previous.get("dang", "")).casefold()
        text = normalize_text(previous.get("noi_dung", ""))

        if not text:
            continue

        if is_document_title_like(text, document_title):
            continue

        if kind == "bullet":
            return strip_bullet_marker(text)

        if kind == "heading":
            return text

        if kind in {"doan_van", "ghi_chu"}:
            if is_table_intro_paragraph(text):
                continue
            break

        if kind == "tieu_de":
            if APPENDIX_TITLE_REGEX.search(text):
                return text
            continue

        break

    return ""

def should_replace_table_title(
    current_title: str,
    inferred_title: str,
    document_title: str,
) -> bool:
    if not inferred_title:
        return False

    if not current_title:
        return True

    return is_document_title_like(current_title, document_title)

def build_content(document: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    document_title = normalize_text(
        document.get("tieu_de", "")
    )

    previous_page_number: int | None = None

    for page_position, page in enumerate(iter_pages(document), start=1):
        page_number_raw = page.get("so_trang", page_position)

        try:
            page_number = int(page_number_raw)
        except (TypeError, ValueError):
            page_number = page_position

        items = page_items(page)
        first_content_index = first_meaningful_item_index(
            items,
            document_title,
            page_number,
        )

        for index, item in enumerate(items):
            item_type = item.get("loai")

            if item_type == "van_ban":
                if item.get("dang") == "metadata":
                    continue

                if is_main_document_title(
                    item,
                    document_title,
                    page_number,
                ):
                    continue

                text_item = build_text_item(item)

                if text_item is not None:
                    result.append(text_item)

                continue

            if item_type != "bang":
                continue

            table_item = build_table_item(item)

            if table_item is None:
                continue

            inferred_title = infer_table_title(
                result,
                document_title,
            )
            current_title = normalize_text(
                table_item.get("tieu_de_bang", "")
            )

            if should_replace_table_title(
                current_title,
                inferred_title,
                document_title,
            ):
                table_item["tieu_de_bang"] = inferred_title
            elif is_document_title_like(
                current_title,
                document_title,
            ):
                table_item["tieu_de_bang"] = ""

            is_first_content_of_page = (
                first_content_index == index
            )
            is_next_page = (
                previous_page_number is not None
                and page_number == previous_page_number + 1
            )

            if (
                is_first_content_of_page
                and is_next_page
                and result
                and result[-1].get("loai") == "bang"
                and tables_are_continuation(
                    result[-1],
                    table_item,
                )
            ):
                merge_table_data(result[-1], table_item)
            else:
                result.append(table_item)

        previous_page_number = page_number

    return result

TERMINAL_PUNCTUATION = (".", ":", ";", "?", "!", "…")

BULLET_PREFIX_REGEX = re.compile(
    r"^\s*(?:[-+•▪◦‣–—]|\(\s*[a-zđ]\s*\)|[a-zđ]\s*[\)\.])\s+",
    re.IGNORECASE,
)

STRUCTURAL_HEADING_REGEXES = (
    re.compile(r"^\s*CHƯƠNG\s+(?:[IVXLCDM]+|\d+)\b", re.IGNORECASE),
    re.compile(r"^\s*ĐIỀU\s+\d+\b", re.IGNORECASE),
    re.compile(r"^\s*PHỤ\s+LỤC(?:\s+(?:[IVXLCDM]+|\d+))?\b", re.IGNORECASE),
    re.compile(r"^\s*MỤC\s+(?:[IVXLCDM]+|\d+(?:\.\d+)*)\b", re.IGNORECASE),
    re.compile(r"^\s*BƯỚC\s+\d+\b", re.IGNORECASE),
    re.compile(r"^\s*(?:[IVXLCDM]+)\s*[\.\)]\s+\S", re.IGNORECASE),
    re.compile(r"^\s*\d+(?:\.\d+)+\s*[\.\)]?\s+\S"),
    re.compile(r"^\s*\d+\s*[\.\)]\s+\S"),
)

NUMBERED_HEADING_CANDIDATE_REGEX = re.compile(
    r"^\s*\d+(?:\.\d+)*(?:\.|\))\s+\S",
    re.UNICODE,
)

URL_OR_EMAIL_REGEX = re.compile(
    r"^(?:https?://|www\.|\S+@\S+\.\S+)",
    re.IGNORECASE,
)

APPENDIX_CAPTION_TAIL_REGEX = re.compile(
    r"^\s*của\s+(?:Hiệu trưởng|Giám đốc|Rector)\b.*\)\s*$",
    re.IGNORECASE,
)

def ends_with_terminal_punctuation(text: str) -> bool:
    value = normalize_text(text).rstrip()
    value = re.sub(r'["”’\')\]]+$', "", value).rstrip()
    return value.endswith(TERMINAL_PUNCTUATION)

def is_bullet_line(text: str) -> bool:
    return bool(BULLET_PREFIX_REGEX.match(normalize_text(text)))

def is_structural_heading_line(text: str) -> bool:
    value = normalize_text(text)

    if not value:
        return False

    return any(
        pattern.match(value)
        for pattern in STRUCTURAL_HEADING_REGEXES
    )

def starts_with_lowercase(text: str) -> bool:
    value = normalize_text(text).lstrip()

    for character in value:
        if character.isalpha():
            return character.islower()

        if character.isdigit():
            return False

    return False

def starts_with_uppercase(text: str) -> bool:
    value = normalize_text(text).lstrip()

    for character in value:
        if character.isalpha():
            return character.isupper()

        if character.isdigit():
            return False

    return False

def is_numbered_heading_candidate(text: str) -> bool:
    return bool(
        NUMBERED_HEADING_CANDIDATE_REGEX.match(
            normalize_text(text)
        )
    )

def is_appendix_caption_tail(text: str) -> bool:
    return bool(
        APPENDIX_CAPTION_TAIL_REGEX.match(
            normalize_text(text)
        )
    )

def should_join_after_wrapped_hyphen(left: str, right: str) -> bool:
    """Return True only when the hyphen is likely a line-wrap artifact.

    Numeric ranges and academic years such as ``2025-\n2026`` must keep the
    hyphen. The conservative rule removes it only when the continuation begins
    with a lowercase letter.
    """
    if not left.endswith("-") or left.endswith(" -"):
        return False

    before_hyphen = left[-2:-1]
    first_right = right[:1]

    if before_hyphen.isdigit() and first_right.isdigit():
        return False

    return starts_with_lowercase(right)


def join_pdf_fragments(left: str, right: str) -> str:
    left = normalize_text(left).rstrip()
    right = normalize_text(right).lstrip()

    if not left:
        return right

    if not right:
        return left

    if should_join_after_wrapped_hyphen(left, right) and not is_bullet_line(right):
        return f"{left[:-1]}{right}"

    if left.endswith("-") and not is_bullet_line(right):
        return f"{left}{right}"

    return f"{left} {right}"

def should_merge_text_fragments(
    previous_text: str,
    current_text: str,
    *,
    previous_kind: str = "",
    current_kind: str = "",
) -> bool:
    previous = normalize_text(previous_text)
    current = normalize_text(current_text)

    if not previous or not current:
        return False

    previous_kind_normalized = normalize_text(previous_kind).casefold()
    current_kind_normalized = normalize_text(current_kind).casefold()

    heading_kinds = {"heading", "tieu_de"}

    if previous_kind_normalized in heading_kinds:
        return False

    if current_kind_normalized in heading_kinds:
        return False

    if is_structural_heading_line(current):
        return False

    if is_bullet_line(current):
        return False

    if (
        is_numbered_heading_candidate(previous)
        and starts_with_uppercase(current)
    ):
        return False

    if ends_with_terminal_punctuation(previous):
        return False

    return True

def merge_wrapped_lines_in_text(text: Any) -> str:
    value = normalize_text(text)

    if "\n" not in value:
        return value

    raw_lines = value.splitlines()
    groups: list[list[str]] = []
    current_group: list[str] = []

    for raw_line in raw_lines:
        line = normalize_text(raw_line)

        if not line:
            if current_group:
                groups.append(current_group)
                current_group = []
            continue

        current_group.append(line)

    if current_group:
        groups.append(current_group)

    normalized_groups: list[str] = []

    for lines in groups:
        merged_lines: list[str] = []

        for line in lines:
            if (
                merged_lines
                and should_merge_text_fragments(
                    merged_lines[-1],
                    line,
                )
            ):
                merged_lines[-1] = join_pdf_fragments(
                    merged_lines[-1],
                    line,
                )
            else:
                merged_lines.append(line)

        normalized_groups.append("\n".join(merged_lines))

    return "\n\n".join(normalized_groups).strip()

def normalize_text_item_content(
    item: dict[str, Any],
) -> dict[str, Any]:
    result = deepcopy(item)
    result["noi_dung"] = merge_wrapped_lines_in_text(
        result.get("noi_dung", "")
    )
    return result

def split_embedded_structures(
    item: dict[str, Any],
) -> list[dict[str, Any]]:
    normalized_item = normalize_text_item_content(item)
    content = normalize_text(
        normalized_item.get("noi_dung", "")
    )

    if not content:
        return []

    if "\n" not in content:
        if is_structural_heading_line(content):
            normalized_item["dang"] = "heading"
        return [normalized_item]

    lines = [
        normalize_text(line)
        for line in content.splitlines()
        if normalize_text(line)
    ]

    if len(lines) <= 1:
        normalized_item["noi_dung"] = content
        return [normalized_item]

    result: list[dict[str, Any]] = []
    buffer: list[str] = []
    base_kind = normalize_text(
        normalized_item.get("dang", "")
    ) or "doan_van"

    def flush_buffer(kind: str | None = None) -> None:
        if not buffer:
            return

        text_value = " ".join(buffer).strip()
        buffer.clear()

        if not text_value:
            return

        result.append({
            "loai": "van_ban",
            "dang": kind or base_kind,
            "noi_dung": text_value,
        })

    for line in lines:
        if is_structural_heading_line(line):
            flush_buffer()
            result.append({
                "loai": "van_ban",
                "dang": "heading",
                "noi_dung": line,
            })
            continue

        if is_bullet_line(line):
            flush_buffer()
            result.append({
                "loai": "van_ban",
                "dang": "bullet",
                "noi_dung": line,
            })
            continue

        if result and result[-1].get("dang") == "heading":
            buffer.append(line)
            continue

        if buffer:
            buffer[-1] = join_pdf_fragments(
                buffer[-1],
                line,
            )
        else:
            buffer.append(line)

    flush_buffer()

    return result or [normalized_item]

def merge_adjacent_text_items(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for raw_item in items:
        item = deepcopy(raw_item)

        if item.get("loai") != "van_ban":
            result.append(item)
            continue

        expanded_items = split_embedded_structures(item)

        for expanded_item in expanded_items:
            content = normalize_text(
                expanded_item.get("noi_dung", "")
            )

            if not content:
                continue

            if (
                is_appendix_caption_tail(content)
                and result
                and result[-1].get("loai") == "van_ban"
                and result[-1].get("dang") == "tieu_de"
                and APPENDIX_TITLE_REGEX.search(
                    normalize_text(
                        result[-1].get("noi_dung", "")
                    )
                )
            ):
                continue

            if not result or result[-1].get("loai") != "van_ban":
                result.append(expanded_item)
                continue

            previous = result[-1]

            if should_merge_text_fragments(
                previous.get("noi_dung", ""),
                content,
                previous_kind=previous.get("dang", ""),
                current_kind=expanded_item.get("dang", ""),
            ):
                previous["noi_dung"] = join_pdf_fragments(
                    previous.get("noi_dung", ""),
                    content,
                )
            else:
                result.append(expanded_item)

    return result

def normalize_document_content(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []

    return merge_adjacent_text_items(items)


ROMAN_FOOTNOTE_REGEX = re.compile(
    r"^(?P<marker>[ivxlcdm]+)\s+(?P<body>[A-ZÀ-ỸĐ].+)$"
)


def lowercase_first(text: str) -> str:
    if not text:
        return text
    return text[:1].lower() + text[1:]


def resolve_roman_footnotes(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Đưa chú thích La Mã bị tách dòng về đúng vị trí tham chiếu."""
    result = deepcopy(items)
    removed: set[int] = set()

    for note_index, note in enumerate(result):
        if note.get("loai") != "van_ban" or note.get("dang") != "ghi_chu":
            continue

        note_text = normalize_text(note.get("noi_dung", ""))
        match = ROMAN_FOOTNOTE_REGEX.match(note_text)
        if not match:
            continue

        marker = re.escape(match.group("marker"))
        body = match.group("body").strip().rstrip(".")
        reference_regex = re.compile(
            rf"(?P<word>\b[^\W\d_]{{2,}}){marker}"
            r"(?=\s+(?:và|hoặc|nhưng|thì)\b|\s*[,.;:])",
            re.IGNORECASE | re.UNICODE,
        )

        for reference_index in range(note_index - 1, -1, -1):
            reference = result[reference_index]
            if reference.get("loai") != "van_ban":
                continue

            reference_text = normalize_text(reference.get("noi_dung", ""))
            candidates = list(reference_regex.finditer(reference_text))
            candidate = next(
                (
                    found for found in reversed(candidates)
                    if re.search(
                        rf"\b{re.escape(found.group('word'))}\b",
                        body,
                        re.IGNORECASE | re.UNICODE,
                    )
                ),
                None,
            )
            if candidate is None:
                continue

            reference["noi_dung"] = (
                reference_text[:candidate.start()]
                + candidate.group("word")
                + f" ({lowercase_first(body)})"
                + reference_text[candidate.end():]
            )
            removed.add(note_index)
            break

    return [
        item for index, item in enumerate(result)
        if index not in removed
    ]

def build_document(source: dict[str, Any]) -> dict[str, Any]:
    content = build_content(source)
    content = normalize_document_content(content)
    content = resolve_roman_footnotes(content)

    return {
        "ma_van_ban": normalize_text(
            source.get("ma_van_ban", "")
        ),
        "ten_file": normalize_text(
            source.get("ten_file", "")
        ),
        "tieu_de": normalize_text(
            source.get("tieu_de", "")
        ),
        "ngay_ban_hanh": normalize_text(
            source.get("ngay_ban_hanh", "")
        ),
        "noi_dung": content,
    }

def document_warnings(
    document: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []

    if not document.get("ma_van_ban"):
        warnings.append("thiếu mã văn bản")

    if not document.get("ngay_ban_hanh"):
        warnings.append("thiếu ngày ban hành")

    if not document.get("tieu_de"):
        warnings.append("thiếu tiêu đề")

    content = document.get("noi_dung", [])

    if not isinstance(content, list) or not content:
        warnings.append("không có nội dung")

    return warnings

def count_content_types(
    document: dict[str, Any],
) -> tuple[int, int]:
    texts = 0
    tables = 0

    for item in document.get("noi_dung", []):
        if item.get("loai") == "van_ban":
            texts += 1
        elif item.get("loai") == "bang":
            tables += 1

    return texts, tables

def output_name(input_path: Path) -> str:
    stem = re.sub(
        r"_metadata(?:\(\d+\))?$",
        "",
        input_path.stem,
        flags=re.IGNORECASE,
    )

    return f"{stem}_document.json"

def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("JSON đầu vào phải là object.")

    return data

def save_json(
    data: dict[str, Any],
    path: Path,
) -> None:
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
        document = build_document(source)

        destination = OUTPUT_DIR / output_name(input_path)
        save_json(document, destination)

        text_count, table_count = count_content_types(
            document
        )

        print(f"[OK] {input_path.name}")
        print(
            f"     Mã văn bản: {document['ma_van_ban'] or '(trống)'}"
        )
        print(f"     Text:        {text_count}")
        print(f"     Bảng logic:  {table_count}")

        warnings = document_warnings(document)

        if warnings:
            print(f"     Cảnh báo:    {'; '.join(warnings)}")

        print(f"     Đầu ra:      {destination}")
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
    print(f"build_document.py — phiên bản {SCRIPT_VERSION}")
    print(f"Đầu vào : {INPUT_DIR}")
    print(f"Đầu ra  : {OUTPUT_DIR}")
    print("-" * 76)

    files = find_input_files()

    if not files:
        print("Không tìm thấy file metadata JSON.")
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
