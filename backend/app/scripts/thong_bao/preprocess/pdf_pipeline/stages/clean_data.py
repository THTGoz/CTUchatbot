from __future__ import annotations

import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..core.utils.bbox import (
    horizontal_overlap_ratio,
    item_bbox as bbox,
    rounded_item_bbox as round_bbox,
    union_bbox,
    vertical_overlap_ratio,
)
from ..core.utils.text import normalize_unicode

SCRIPT_VERSION = "5.2-visible-metadata-only"

ROOT_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT_DIR / "output" / "01_raw_blocks"
OUTPUT_DIR = ROOT_DIR / "output" / "02_clean"
JSON_INDENT = 2

EXACT_HEADER_REGEXES = [
    re.compile(r"^BỘ GIÁO DỤC VÀ ĐÀO TẠO$", re.I),
    re.compile(r"^ĐẠI HỌC CẦN THƠ$", re.I),
    re.compile(r"^TRƯỜNG ĐẠI HỌC CẦN THƠ$", re.I),
    re.compile(r"^CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM$", re.I),
    re.compile(r"^ĐỘC LẬP\s*[-–—]\s*TỰ DO\s*[-–—]\s*HẠNH PHÚC$", re.I),

    re.compile(
        r"^BỘ GIÁO DỤC VÀ ĐÀO TẠO\s+"
        r"CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM$",
        re.I,
    ),
    re.compile(
        r"^(?:ĐẠI HỌC CẦN THƠ|TRƯỜNG ĐẠI HỌC CẦN THƠ)\s+"
        r"ĐỘC LẬP\s*[-–—]\s*TỰ DO\s*[-–—]\s*HẠNH PHÚC$",
        re.I,
    ),
]

AGENCY_HEADER_REGEX = re.compile(
    r"^(?:PHÒNG|KHOA|VIỆN|TRUNG TÂM|TRƯỜNG)\s+[A-ZÀ-ỸĐ0-9&().,\-/ ]+$",
    re.I,
)

RECIPIENT_START_REGEX = re.compile(r"^KÍNH\s+GỬI\s*:?", re.I)
FOOTER_START_REGEX = re.compile(r"^NƠI\s+NHẬN\s*:?", re.I)

SIGNATURE_TITLE_REGEX = re.compile(
    r"^(?:(?:KT|TL|TUQ|Q)\.?\s*)?"
    r"(?:HIỆU TRƯỞNG|PHÓ HIỆU TRƯỞNG|"
    r"TRƯỞNG PHÒNG|PHÓ TRƯỞNG PHÒNG|"
    r"GIÁM ĐỐC|PHÓ GIÁM ĐỐC|"
    r"TRƯỞNG KHOA|PHÓ TRƯỞNG KHOA|"
    r"VIỆN TRƯỞNG|PHÓ VIỆN TRƯỞNG)"
    r"(?:\s+(?:TRƯỜNG|KHOA|PHÒNG|VIỆN|TRUNG TÂM)\b"
    r"[A-ZÀ-ỸĐ0-9&().,\-/ ]*)?$",
    re.I,
)

AGENCY_CONTINUATION_REGEX = re.compile(
    r"^(?:VÀ|&)"
    r"(?:\s+[A-ZÀ-ỸĐ0-9&().,\-/]+){1,10}$",
    re.I,
)

CLOSING_REGEX = re.compile(
    r"^(?:TRÂN TRỌNG(?: KÍNH CHÀO)?|KÍNH CHÀO)\s*[./]*$",
    re.I,
)

PERSON_NAME_REGEX = re.compile(
    r"^[A-ZÀ-ỸĐ][a-zà-ỹđ]+(?:\s+[A-ZÀ-ỸĐ][a-zà-ỹđ]+){1,5}$"
)

DOCUMENT_NUMBER_REGEX = re.compile(r"^SỐ\s*:?\s*(?=\d|/)", re.I)
DATE_REGEX = re.compile(r"^CẦN THƠ\s*,?\s*NGÀY\b", re.I)
PURE_NUMBER_REGEX = re.compile(r"^\d{1,6}$")

TITLE_REGEX = re.compile(
    r"^(?:THÔNG BÁO|QUYẾT ĐỊNH|QUY ĐỊNH|KẾ HOẠCH|"
    r"HƯỚNG DẪN|BÁO CÁO|CÔNG VĂN|PHỤ LỤC|DANH SÁCH)\b",
    re.I,
)

HEADING_REGEX = re.compile(
    r"^(?:"
    r"(?:\d+\.\d+(?:\.\d+)*\.?|\d+[.)])\s+\S|"
    r"[IVXLCDM]+\.\s+\S|"
    r"BƯỚC\s+\d+[.:]?\s*\S*"
    r")",
    re.I,
)

BULLET_REGEX = re.compile(r"^\s*([-–—•+])\s*(.*)$")
NOTE_REGEX = re.compile(r"^(?:LƯU Ý|GHI CHÚ|CHÚ THÍCH)\s*:", re.I)
SUBJECT_REGEX = re.compile(r"^(?:V\s*/\s*v|Về\s+việc)\b", re.I)
LIST_SUMMARY_REGEX = re.compile(r"^Danh\s+sách\s+có\s*:", re.I)
FOOTNOTE_REGEX = re.compile(r"^[ivxlcdm]+\s+\S", re.I)
URL_REGEX = re.compile(r"https?://\S+", re.I)
URL_START_REGEX = re.compile(r"^(?:https?://|www\.)\S+", re.I)
EMAIL_START_REGEX = re.compile(
    r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b",
    re.I,
)
OPENING_START_REGEX = re.compile(r'^[\(\[\{“"\']')

def normalize_line(text: str) -> str:
    text = normalize_unicode(text).replace("\t", " ")
    text = re.sub(r"[ ]{2,}", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?%)\]])", r"\1", text)
    if not URL_REGEX.search(text):
        text = re.sub(r"([;:!?])(?=\S)", r"\1 ", text)
    return re.sub(r"[ ]{2,}", " ", text).strip()

def normalize_cell(value: Any) -> str:
    if value is None:
        return ""

    lines = [normalize_line(x) for x in str(value).splitlines()]
    text = " ".join(x for x in lines if x).strip()

    text = re.sub(r"\b(\d{1,2})\s*:\s*(\d{2})\b", r"\1:\2", text)
    return text

def is_all_caps(text: str) -> bool:
    chars = [c for c in text if c.isalpha()]
    return bool(chars) and all(c.isupper() for c in chars)

def starts_lower(text: str) -> bool:
    match = re.search(r"[A-Za-zÀ-ỹĐđ]", text)
    return bool(match and match.group(0).islower())

def ends_sentence(text: str) -> bool:
    return bool(re.search(r"[.!?;:]\s*$", text))

def ends_strong_sentence(text: str) -> bool:
    return bool(re.search(r"[.!?]\s*$", text))

def starts_url_or_email(text: str) -> bool:
    text = text.strip()
    return bool(
        URL_START_REGEX.match(text)
        or EMAIL_START_REGEX.match(text)
    )

def starts_with_opening_mark(text: str) -> bool:
    return bool(OPENING_START_REGEX.match(text.strip()))

def is_likely_continuation(text: str) -> bool:
    text = text.strip()
    if not text:
        return False

    return bool(
        starts_lower(text)
        or starts_with_opening_mark(text)
        or starts_url_or_email(text)
    )

def is_page_number_block(
    item: dict[str, Any],
    page_width: float,
    page_height: float,
) -> bool:
    if item.get("loai") != "van_ban":
        return False

    text = normalize_line(str(item.get("noi_dung", "")))
    if not re.fullmatch(r"\d{1,3}", text):
        return False

    if page_width <= 0 or page_height <= 0:
        return False

    x0, y0, x1, y1 = bbox(item)
    center_x = (x0 + x1) / 2
    page_center_x = page_width / 2

    near_top = y1 <= page_height * 0.08
    near_bottom = y0 >= page_height * 0.90
    near_center = abs(center_x - page_center_x) <= page_width * 0.08
    compact_block = (x1 - x0) <= page_width * 0.08

    return (near_top or near_bottom) and near_center and compact_block

def is_exact_header(line: str) -> bool:
    if any(rx.fullmatch(line) for rx in EXACT_HEADER_REGEXES):
        return True
    return bool(
        AGENCY_HEADER_REGEX.fullmatch(line)
        and is_all_caps(line)
        and len(line) <= 120
    )


def is_agency_header_line(line: str) -> bool:
    line = normalize_line(line)
    return bool(
        AGENCY_HEADER_REGEX.fullmatch(line)
        and is_all_caps(line)
        and len(line) <= 120
    )


def is_agency_header_continuation(line: str) -> bool:
    line = normalize_line(line)
    return bool(
        AGENCY_CONTINUATION_REGEX.fullmatch(line)
        and is_all_caps(line)
        and len(line) <= 100
    )


def is_top_page_item(
    item: dict[str, Any],
    page_height: float,
    *,
    ratio: float = 0.24,
) -> bool:
    if page_height <= 0:
        return False
    return bbox(item)[1] <= page_height * ratio

def is_document_title_text(text: str) -> bool:
    text = text.strip()
    if LIST_SUMMARY_REGEX.match(text):
        return False
    return bool(TITLE_REGEX.match(text))

def is_heading_text(text: str) -> bool:
    text = text.strip()
    return bool(
        is_document_title_text(text)
        or HEADING_REGEX.match(text)
        or (is_all_caps(text) and len(text) <= 240)
    )

def classify_text(
    text: str,
    *,
    y0: float = 0.0,
    page_height: float = 0.0,
) -> str:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if not lines:
        return "doan_van"

    first = lines[0]
    joined = "\n".join(lines)

    if DOCUMENT_NUMBER_REGEX.match(first) or DATE_REGEX.match(first):
        return "metadata"

    if LIST_SUMMARY_REGEX.match(first):
        return "ghi_chu"

    if NOTE_REGEX.match(first) or first.startswith("("):
        return "ghi_chu"

    near_bottom = page_height > 0 and y0 >= page_height * 0.90
    if near_bottom and FOOTNOTE_REGEX.match(first):
        return "ghi_chu"

    if BULLET_REGEX.match(first):
        return "bullet"

    if SUBJECT_REGEX.match(first):
        return "tieu_de"

    if is_document_title_text(first):
        return "tieu_de"

    if HEADING_REGEX.match(first) or (is_all_caps(joined) and len(joined) <= 240):
        return "heading"

    return "doan_van"

def clean_block_lines(
    raw_text: str,
    *,
    y0: float,
    page_height: float,
) -> list[str]:
    source = [normalize_line(x) for x in normalize_unicode(raw_text).splitlines()]

    result: list[str] = []
    recipient_mode = False
    signature_mode = False
    agency_header_mode = False
    near_top = page_height > 0 and y0 <= page_height * 0.24

    for line in source:
        if not line:
            continue

        if FOOTER_START_REGEX.match(line):
            break

        if RECIPIENT_START_REGEX.match(line):
            recipient_mode = True
            agency_header_mode = False
            continue

        if recipient_mode:
            if BULLET_REGEX.match(line):
                continue
            if len(line) >= 35 and not is_all_caps(line):
                recipient_mode = False
            else:
                continue

        if is_exact_header(line):
            # Một block đầu trang có thể chứa hai cột header xen kẽ theo thứ tự
            # đọc PDF, ví dụ: tên trường -> quốc hiệu -> phần tiếp nối "VÀ ...".
            # Khi đã gặp tên cơ quan trong cùng block, không tắt trạng thái chỉ vì
            # gặp một dòng header khác ở cột bên phải; nhờ đó phần tiếp nối của
            # tên cơ quan vẫn được loại chính xác.
            if is_agency_header_line(line):
                agency_header_mode = True
            continue

        if (
            near_top
            and agency_header_mode
            and is_agency_header_continuation(line)
        ):
            continue

        if (
            DOCUMENT_NUMBER_REGEX.match(line)
            or DATE_REGEX.match(line)
            or is_document_title_text(line)
        ):
            agency_header_mode = False

        if SIGNATURE_TITLE_REGEX.fullmatch(line):
            signature_mode = True
            continue

        if CLOSING_REGEX.fullmatch(line):
            continue

        if PERSON_NAME_REGEX.fullmatch(line):
            near_bottom = page_height > 0 and y0 >= page_height * 0.58
            if signature_mode or near_bottom:
                continue

        result.append(line)

    return result

def normalize_bullet(line: str) -> str:
    match = BULLET_REGEX.match(line)
    if not match:
        return line
    marker, content = match.groups()
    if marker in {"–", "—", "•"}:
        marker = "-"
    return f"{marker} {content}".rstrip()

def is_explicit_structure_start(line: str) -> bool:
    line = line.strip()
    return bool(
        DOCUMENT_NUMBER_REGEX.match(line)
        or DATE_REGEX.match(line)
        or SUBJECT_REGEX.match(line)
        or BULLET_REGEX.match(line)
        or HEADING_REGEX.match(line)
        or NOTE_REGEX.match(line)
        or LIST_SUMMARY_REGEX.match(line)
        or is_document_title_text(line)
        or (is_all_caps(line) and len(line) <= 240)
    )

def should_join_lines(previous: str, current: str) -> bool:
    previous = previous.strip()
    current = current.strip()

    if not previous or not current:
        return False

    if is_explicit_structure_start(current):
        return False

    if starts_url_or_email(current):
        return previous.endswith(":") or not ends_strong_sentence(previous)

    if starts_with_opening_mark(current):
        return not ends_strong_sentence(previous)

    if starts_lower(current):
        return not ends_strong_sentence(previous)

    if ends_sentence(previous):
        return False

    return len(previous) >= 58

def should_remove_line_break_hyphen(previous: str, current: str) -> bool:
    """Chỉ bỏ dấu gạch nối khi nó nhiều khả năng là ngắt từ qua dòng."""
    if not previous.endswith("-") or previous.endswith(" -"):
        return False

    before_hyphen = previous[-2:-1]
    first_current = current[:1]

    # Giữ dấu gạch nối trong khoảng số, ví dụ: 2025-\n2026.
    if before_hyphen.isdigit() and first_current.isdigit():
        return False

    return starts_lower(current)


def append_continuation(previous: str, current: str) -> str:
    if should_remove_line_break_hyphen(previous, current):
        return previous[:-1] + current

    return f"{previous} {current}".strip()


def is_split_legal_code(previous: str, current: str) -> bool:
    """Nhận diện phần ký hiệu văn bản bị xuống dòng tại dấu gạch nối."""
    return bool(
        re.search(r"\b\d{1,6}/[A-ZĐ]{1,12}$", previous.strip(), re.I)
        and re.match(r"^-\s*[A-ZĐ]{2,12}\b", current.strip(), re.I)
    )

def segment_lines(lines: list[str]) -> list[str]:
    segments: list[list[str]] = []

    for raw in lines:
        line = normalize_bullet(raw)
        if not line:
            continue

        if not segments:
            segments.append([line])
            continue

        current = segments[-1]
        first = current[0]

        if is_split_legal_code(current[-1], line):
            current[-1] = append_continuation(current[-1], line)
            continue

        if DATE_REGEX.match(line) and DOCUMENT_NUMBER_REGEX.match(first):
            current.append(line)
            continue

        if SUBJECT_REGEX.match(line) and is_document_title_text(first):
            current.append(line)
            continue

        if (
            is_document_title_text(first)
            and is_all_caps(line)
            and not HEADING_REGEX.match(line)
        ):
            current.append(line)
            continue

        if line.startswith("(") and (
            is_document_title_text(first)
            or first.upper().startswith("PHỤ LỤC")
            or first.upper().startswith("DANH SÁCH")
        ):
            current.append(line)
            continue

        if is_explicit_structure_start(line):
            segments.append([line])
            continue

        if should_join_lines(current[-1], line):
            current[-1] = append_continuation(current[-1], line)
        else:
            current.append(line)

    return ["\n".join(segment).strip() for segment in segments if segment]

def clean_text_items(
    item: dict[str, Any],
    page_height: float,
) -> list[dict[str, Any]]:
    b = bbox(item)
    lines = clean_block_lines(
        str(item.get("noi_dung", "")),
        y0=b[1],
        page_height=page_height,
    )

    result: list[dict[str, Any]] = []
    for text in segment_lines(lines):
        if not text:
            continue
        result.append(
            {
                "loai": "van_ban",
                "dang": classify_text(text, y0=b[1], page_height=page_height),
                "bbox": round_bbox(item),
                "noi_dung": text,
            }
        )

    return result

def clean_table_item(item: dict[str, Any]) -> dict[str, Any] | None:
    rows = item.get("du_lieu", [])
    if not isinstance(rows, list):
        return None

    cleaned: list[list[str]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        new_row = [normalize_cell(cell) for cell in row]
        if any(new_row):
            cleaned.append(new_row)

    if not cleaned:
        return None

    return {
        "loai": "bang",
        "bbox": round_bbox(item),
        "tieu_de_bang": normalize_line(str(item.get("tieu_de_bang", ""))),
        "du_lieu": cleaned,
    }

def text_lines(item: dict[str, Any]) -> list[str]:
    return [x.strip() for x in str(item.get("noi_dung", "")).splitlines() if x.strip()]

def looks_like_number_date_overlay(item: dict[str, Any]) -> bool:
    lines = text_lines(item)
    return bool(lines) and len(lines) <= 3 and all(PURE_NUMBER_REGEX.fullmatch(x) for x in lines)


def repair_metadata_overlays(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Loại lớp số rời nằm chồng lên vùng metadata mà không dùng nó để điền dữ liệu.

    Các lớp này có thể do ký số/OCR tạo ra và không nhất thiết hiển thị khi mở
    PDF. Metadata chính thức chỉ giữ phần chữ có sẵn trong dòng mẫu nhìn thấy.
    """
    result = deepcopy(items)
    removed: set[int] = set()

    for meta_idx, meta in enumerate(result):
        if meta.get("loai") != "van_ban":
            continue

        lines = text_lines(meta)
        if not any(DOCUMENT_NUMBER_REGEX.match(x) for x in lines):
            continue

        mb = bbox(meta)
        candidates: list[tuple[float, int]] = []

        # Bỏ các dòng số rời bị nhúng ở cuối chính block metadata.
        visible_lines = [lines[0]] + [
            line for line in lines[1:] if not PURE_NUMBER_REGEX.fullmatch(line)
        ]
        meta["noi_dung"] = "\n".join(visible_lines)
        meta["dang"] = "metadata"

        for idx, candidate in enumerate(result):
            if idx == meta_idx or idx in removed:
                continue
            if candidate.get("loai") != "van_ban":
                continue
            if not looks_like_number_date_overlay(candidate):
                continue

            cb = bbox(candidate)
            v_overlap = vertical_overlap_ratio(mb, cb)
            center_y_distance = abs(((mb[1] + mb[3]) / 2) - ((cb[1] + cb[3]) / 2))

            if v_overlap <= 0 and center_y_distance > 20:
                continue

            score = v_overlap * 10 - center_y_distance / 100
            candidates.append((score, idx))

        if candidates:
            _, overlay_idx = max(candidates)
            meta["bbox"] = [
                round(x, 2)
                for x in union_bbox(bbox(meta), bbox(result[overlay_idx]))
            ]
            removed.add(overlay_idx)

    return [item for idx, item in enumerate(result) if idx not in removed]

def remove_split_header_continuations(
    items: list[dict[str, Any]],
    page_height: float,
) -> list[dict[str, Any]]:
    """
    Loại phần tiếp nối của tên cơ quan khi PDF tách header thành nhiều block.

    Chỉ áp dụng ở vùng đầu trang và chỉ khi block hiện tại là cụm viết hoa
    bắt đầu bằng "VÀ" hoặc "&". Việc giới hạn theo vị trí giúp tránh xóa nhầm
    các cụm tương tự trong nội dung chính.
    """
    result: list[dict[str, Any]] = []
    previous_was_agency_header = False

    for item in items:
        if item.get("loai") != "van_ban":
            result.append(item)
            previous_was_agency_header = False
            continue

        content = normalize_line(str(item.get("noi_dung", "")))
        top_item = is_top_page_item(item, page_height)

        if (
            top_item
            and previous_was_agency_header
            and is_agency_header_continuation(content)
        ):
            continue

        previous_was_agency_header = bool(
            top_item and is_agency_header_line(content)
        )

        if (
            DOCUMENT_NUMBER_REGEX.match(content)
            or DATE_REGEX.match(content)
            or is_document_title_text(content)
        ):
            previous_was_agency_header = False

        result.append(item)

    return result


def should_merge_items(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if previous.get("loai") != "van_ban" or current.get("loai") != "van_ban":
        return False

    p = str(previous.get("noi_dung", "")).strip()
    c = str(current.get("noi_dung", "")).strip()
    if not p or not c:
        return False

    previous_kind = previous.get("dang")
    current_kind = current.get("dang")

    if current_kind in {"metadata", "tieu_de", "heading", "bullet", "ghi_chu"}:
        return False

    pb, cb = bbox(previous), bbox(current)
    gap = cb[1] - pb[3]
    if not (-2 <= gap <= 16):
        return False
    if horizontal_overlap_ratio(pb, cb) <= 0:
        return False

    if previous_kind == "bullet":
        if starts_url_or_email(c):
            return p.endswith(":") or not ends_strong_sentence(p)
        if starts_with_opening_mark(c) or starts_lower(c):
            return not ends_strong_sentence(p)
        return not ends_sentence(p) and len(p) >= 55

    if previous_kind == "tieu_de":
        unmatched_parenthesis = p.count("(") > p.count(")")
        return (
            not ends_strong_sentence(p)
            and (
                starts_lower(c)
                or (
                    unmatched_parenthesis
                    and (
                        starts_with_opening_mark(c)
                        or starts_url_or_email(c)
                    )
                )
            )
        )

    if previous_kind in {"metadata", "heading", "ghi_chu"}:
        return False

    if starts_url_or_email(c):
        return p.endswith(":") or not ends_strong_sentence(p)

    if starts_with_opening_mark(c) or starts_lower(c):
        return not ends_strong_sentence(p)

    if ends_sentence(p):
        return False

    return len(p) >= 65

def demote_numbered_note_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = deepcopy(items)
    in_numbered_note = False

    for item in result:
        if item.get("loai") != "van_ban":
            continue

        content = str(item.get("noi_dung", "")).strip()
        dang = str(item.get("dang", "")).strip()

        if dang == "ghi_chu" and NOTE_REGEX.match(content):
            in_numbered_note = True
            continue

        if not in_numbered_note:
            continue

        if dang == "heading" and re.match(r"^\d+[.)]\s+\S", content):
            item["dang"] = "doan_van"
            continue

        if dang in {"doan_van", "bullet"}:
            continue

        if dang in {"tieu_de", "metadata"}:
            in_numbered_note = False

    return result

def merge_text_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for item in items:
        if result and should_merge_items(result[-1], item):
            prev = result[-1]
            separator = " "
            prev["noi_dung"] = f"{prev['noi_dung']}{separator}{item['noi_dung']}".strip()
            prev["bbox"] = [
                round(x, 2)
                for x in union_bbox(bbox(prev), bbox(item))
            ]
            prev["dang"] = classify_text(prev["noi_dung"])
        else:
            result.append(deepcopy(item))

    return result

def is_attachment_title(text: str) -> bool:
    text = str(text).strip()
    if not text:
        return False

    first_line = next(
        (line.strip() for line in text.splitlines() if line.strip()),
        "",
    )

    return bool(
        re.match(r"^(?:PHỤ\s+LỤC|DANH\s+SÁCH)\b", first_line, re.I)
        or re.search(r"\b(?:đính\s+kèm|kèm\s+theo)\b", text, re.I)
    )

def table_header_signature(table: dict[str, Any]) -> tuple[str, ...]:
    rows = table.get("du_lieu", [])
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], list):
        return ()

    return tuple(
        re.sub(r"\s+", " ", str(cell)).strip().casefold()
        for cell in rows[0]
    )

def candidate_table_title(items: list[dict[str, Any]], table_index: int) -> str:
    checked_text_items = 0

    for idx in range(table_index - 1, -1, -1):
        item = items[idx]
        if item.get("loai") != "van_ban":
            continue

        checked_text_items += 1
        content = str(item.get("noi_dung", "")).strip()
        dang = str(item.get("dang", "")).strip()

        if not content:
            continue

        if dang == "bullet":
            return content

        if dang == "heading":
            return content

        if dang == "tieu_de" and is_attachment_title(content):
            lines = [
                line.strip()
                for line in content.splitlines()
                if line.strip() and not line.strip().startswith("(")
            ]
            return "\n".join(lines)

        if checked_text_items >= 4:
            break

    return ""

def attach_local_titles(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = deepcopy(items)

    for idx, item in enumerate(result):
        if item.get("loai") != "bang":
            continue
        if str(item.get("tieu_de_bang", "")).strip():
            continue
        item["tieu_de_bang"] = candidate_table_title(result, idx)

    return result

def propagate_titles_across_pages(document: dict[str, Any]) -> None:
    previous_title = ""
    previous_signature: tuple[str, ...] = ()

    for page in document.get("trang", []):
        for item in page.get("items", []):
            if item.get("loai") != "bang":
                continue

            signature = table_header_signature(item)
            title = str(item.get("tieu_de_bang", "")).strip()

            if (
                not title
                and previous_title
                and signature
                and signature == previous_signature
            ):
                item["tieu_de_bang"] = previous_title
                title = previous_title

            if title:
                previous_title = title
                previous_signature = signature
            elif signature != previous_signature:
                previous_title = ""
                previous_signature = signature

def item_reading_order(item: dict[str, Any]) -> tuple[float, float, int]:
    x0, y0, _, _ = bbox(item)
    priority = 0 if item.get("loai") == "van_ban" else 1
    return y0, x0, priority

def normalized_page_size(page: dict[str, Any]) -> list[float]:
    raw = page.get("kich_thuoc", [0, 0])
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return [0.0, 0.0]
    try:
        return [round(float(raw[0]), 2), round(float(raw[1]), 2)]
    except (TypeError, ValueError):
        return [0.0, 0.0]

def safe_page_number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

def clean_page(page: dict[str, Any]) -> dict[str, Any]:
    page_size = normalized_page_size(page)
    page_width = page_size[0]
    page_height = page_size[1]

    source_items = page.get("items", [])
    if not isinstance(source_items, list):
        source_items = []

    items: list[dict[str, Any]] = []
    for source_item in source_items:
        if not isinstance(source_item, dict):
            continue

        if source_item.get("loai") == "van_ban":
            items.extend(clean_text_items(source_item, page_height))
            continue

        if source_item.get("loai") == "bang":
            cleaned = clean_table_item(source_item)
            if cleaned:
                items.append(cleaned)

    items.sort(key=item_reading_order)

    items = remove_split_header_continuations(items, page_height)
    items = repair_metadata_overlays(items)

    items = [
        item
        for item in items
        if not is_page_number_block(item, page_width, page_height)
    ]

    items = merge_text_items(items)
    items = demote_numbered_note_items(items)
    items = attach_local_titles(items)

    return {
        "so_trang": safe_page_number(page.get("so_trang", 0)),
        "kich_thuoc": page_size,
        "items": items,
    }

def clean_document(source: dict[str, Any]) -> dict[str, Any]:
    pages = source.get("trang", [])
    if not isinstance(pages, list):
        pages = []

    document = {
        "ten_file": str(source.get("ten_file", "")).strip(),
        "trang": [clean_page(page) for page in pages if isinstance(page, dict)],
    }

    propagate_titles_across_pages(document)
    return document

def output_name(input_path: Path) -> str:
    stem = re.sub(r"_raw(?:\(\d+\))?$", "", input_path.stem, flags=re.I)
    return f"{stem}_clean.json"

def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("JSON đầu vào phải là object.")

    return data

def save_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=JSON_INDENT)
        file.write("\n")

def find_input_files() -> list[Path]:
    if not INPUT_DIR.exists():
        return []
    return sorted(path for path in INPUT_DIR.glob("*_raw*.json") if path.is_file())

def process_file(input_path: Path) -> bool:
    try:
        source = load_json(input_path)
        cleaned = clean_document(source)
        destination = OUTPUT_DIR / output_name(input_path)
        save_json(cleaned, destination)

        print(f"[OK] {input_path.name}")
        print(f"     -> {destination}")
        return True
    except Exception as error:
        print(f"[LỖI] {input_path.name}: {error}")
        return False

def main() -> int:
    print(f"clean_data.py — {SCRIPT_VERSION}")
    print(f"Đầu vào : {INPUT_DIR}")
    print(f"Đầu ra  : {OUTPUT_DIR}")
    print("-" * 72)

    files = find_input_files()
    if not files:
        print("Không tìm thấy JSON đầu vào.")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    success = sum(process_file(path) for path in files)

    print("-" * 72)
    print(f"Hoàn thành: {success}/{len(files)} file.")
    return 0 if success == len(files) else 1

if __name__ == "__main__":
    sys.exit(main())
