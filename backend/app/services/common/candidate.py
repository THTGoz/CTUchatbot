"""Candidate contract và các bước ranking/context dùng chung cho mọi domain."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any, TypedDict


DOMAIN_QCHV = "qchv"
DOMAIN_CTDT = "ctdt"
DOMAIN_THONG_BAO = "thong_bao"

EXPANSION_SOURCES = {
    "document_muc_expansion",
    "document_related_muc_expansion",
    "document_table_expansion",
    "document_table_row_expansion",
}

logger = logging.getLogger("app.thong_bao.context")


class Candidate(TypedDict):
    node_id: str
    label: str
    cosine_score: float
    properties: dict[str, Any]
    source: str
    domain: str
    metadata: dict[str, Any]


def make_candidate(
    *,
    node_id: object,
    label: object,
    cosine_score: object,
    properties: dict[str, Any] | None,
    source: str,
    domain: str,
    metadata: dict[str, Any] | None = None,
) -> Candidate:
    cleaned_properties = dict(properties or {})
    for key in tuple(cleaned_properties):
        lowered = str(key).casefold()
        if lowered == "embedding" or lowered.endswith("_embedding") or lowered.endswith("_vector"):
            cleaned_properties.pop(key, None)
    try:
        score = float(cosine_score or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return {
        "node_id": str(node_id or ""),
        "label": str(label or "Node"),
        "cosine_score": score,
        "properties": cleaned_properties,
        "source": str(source),
        "domain": str(domain),
        "metadata": dict(metadata or {}),
    }


def merge_candidates(groups: Iterable[Iterable[Candidate]]) -> list[Candidate]:
    """Deduplicate by domain/node while protecting an exact match."""
    merged: dict[tuple[str, str], Candidate] = {}
    for candidate in (item for group in groups for item in group):
        key = (candidate["domain"], candidate["node_id"])
        current = merged.get(key)
        candidate_exact = candidate["source"] == "exact"
        current_exact = current is not None and current["source"] == "exact"
        if (
            current is None
            or (candidate_exact and not current_exact)
            or (
                candidate_exact == current_exact
                and candidate["cosine_score"] > current["cosine_score"]
            )
        ):
            merged[key] = candidate
    return sorted(
        merged.values(),
        key=lambda item: item["cosine_score"],
        reverse=True,
    )


def select_top_k(candidates: Iterable[Candidate], top_k: int) -> list[Candidate]:
    """Apply global cosine ranking, with the legacy exact-anchor protection."""
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero")
    unique = merge_candidates([candidates])
    exact = [item for item in unique if item["source"] == "exact"]
    ranked = [item for item in unique if item["source"] != "exact"]
    exact.sort(key=lambda item: item["cosine_score"], reverse=True)
    ranked.sort(key=lambda item: item["cosine_score"], reverse=True)
    return (exact + ranked)[:top_k]


_PREFERRED_PROPERTY_KEYS = (
    "ma_hoc_phan",
    "ten_hoc_phan",
    "so_tin_chi",
    "ma_nganh",
    "ten_nganh_vi",
    "ten_khoa",
    "khoa",
    "he",
    "tong_tin_chi",
    "ten_khoi",
    "tieu_de",
    "ten",
    "so",
    "ky_hieu",
    "path",
    "noi_dung",
    "text_embed",
    "noi_dung_dong",
    "gia_tri",
)


def _display_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _useful_properties(candidate: Candidate) -> list[str]:
    properties = candidate["properties"]
    keys = [key for key in _PREFERRED_PROPERTY_KEYS if key in properties]
    keys.extend(key for key in properties if key not in keys)
    lines: list[str] = []
    for key in keys:
        value = properties.get(key)
        if value in (None, "", []):
            continue
        lines.append(f"{key}: {_display_value(value)}")
        if len(lines) >= 12:
            break
    return lines


def _useful_metadata(candidate: Candidate) -> list[str]:
    metadata = candidate["metadata"]
    lines = []
    for key in ("ten_van_ban", "ten_thong_bao", "nam_hoc", "hoc_ky"):
        value = metadata.get(key)
        if value not in (None, ""):
            lines.append(f"{key}: {_display_value(value)}")
    relations = metadata.get("relationships")
    if relations:
        lines.append(f"quan_he: {_display_value(relations)}")
    return lines


def _render_root(position: int, candidate: Candidate) -> str:
    lines = [
        f"[NGUỒN {position}]",
        f"Miền: {candidate['domain']}",
        f"Loại node: {candidate['label']}",
        *_useful_metadata(candidate),
        *_useful_properties(candidate),
    ]
    return "\n".join(lines)


def _render_expansion(candidate: Candidate) -> str:
    prefix = "- Mở rộng liên quan"
    details = _useful_properties(candidate)
    relationship = candidate["metadata"].get("relationship")
    if relationship:
        direction = candidate["metadata"].get("direction", "outgoing")
        details.insert(0, f"{direction}: {relationship}")
    if not details:
        return prefix
    return "\n".join([f"{prefix}: {details[0]}", *(f"  {line}" for line in details[1:])])


def _short_text(value: Any, limit: int = 1000) -> str:
    text = " ".join(_display_value(value).split())
    return text if len(text) <= limit else f"{text[:limit].rstrip()}…"


def _row_text(candidate: Candidate, headers: list[Any] | None = None) -> str:
    values = candidate["properties"].get("gia_tri")
    if isinstance(values, list):
        columns = headers or candidate["metadata"].get("table_headers") or []
        labelled_values = [
            f"{str(header).strip()}: {str(values[index]).strip()}"
            for index, header in enumerate(columns)
            if index < len(values)
            and str(header).strip()
            and str(values[index]).strip()
        ]
        if labelled_values:
            return " | ".join(labelled_values)
        rendered = " | ".join(str(value).strip() for value in values)
        if rendered.strip(" |"):
            return rendered
    return _short_text(candidate["properties"].get("noi_dung_dong") or "")


def _muc_text(candidate: Candidate) -> str:
    properties = candidate["properties"]
    return _short_text(properties.get("noi_dung") or properties.get("text") or "")


def _muc_label(properties: dict[str, Any]) -> str:
    symbol = str(properties.get("ky_hieu") or "").strip()
    return f"Mục {symbol}" if symbol else "Mục không ký hiệu"


def _render_notification_header(seed: Candidate) -> list[str]:
    metadata = seed["metadata"]
    provenance = metadata.get("provenance") or {}
    notice = provenance.get("thong_bao") or {}
    document = provenance.get("tai_lieu") or {}
    notice_title = (
        notice.get("tieu_de")
        or metadata.get("ten_thong_bao")
        or notice.get("id")
        or metadata.get("notification_id")
    )
    lines: list[str] = []
    if notice_title:
        lines.append(f"Thông báo: {_short_text(notice_title)}")
    school_year = notice.get("nam_hoc") or metadata.get("nam_hoc")
    semester = notice.get("hoc_ky") or metadata.get("hoc_ky")
    if school_year:
        lines.append(f"Năm học: {_display_value(school_year)}")
    if semester:
        lines.append(f"Học kỳ: {_display_value(semester)}")
    if document.get("ten_tai_lieu"):
        lines.append(f"Tài liệu: {_short_text(document['ten_tai_lieu'])}")
    return lines


def _render_document_mucs(
    seed: Candidate,
    expansions: list[Candidate],
    *,
    heading: str = "CÁC MỤC CÙNG TÀI LIỆU:",
) -> list[str]:
    """Render mỗi Muc expansion đúng một lần trong bundle của seed."""
    sections = [
        item for item in expansions
        if item["source"] == "document_muc_expansion"
    ]
    provenance = seed["metadata"].get("provenance") or {}
    owner_section = provenance.get("muc") or {}
    if not sections and seed["label"] == "DongBang" and owner_section:
        sections = [make_candidate(
            node_id=owner_section.get("id"),
            label="Muc",
            cosine_score=0.0,
            properties=owner_section,
            source="document_muc_expansion",
            domain=DOMAIN_THONG_BAO,
        )]
    if not sections:
        return []

    lines = [heading]
    seen: set[str] = set()
    for section in sections:
        properties = section["properties"]
        identity = str(properties.get("id") or section["node_id"])
        if identity in seen:
            continue
        seen.add(identity)
        content = _muc_text(section)
        label = _muc_label(properties)
        lines.append(f"- {label}: {content}" if content else f"- {label}")
    return lines


def _render_muc_tables(expansions: list[Candidate]) -> list[str]:
    tables = [
        item for item in expansions
        if item["source"] == "document_table_expansion"
    ]
    rows = [
        item for item in expansions
        if item["source"] == "document_table_row_expansion"
    ]
    lines: list[str] = []
    for position, table in enumerate(tables, start=1):
        properties = table["properties"]
        table_id = table["node_id"]
        title = str(properties.get("tieu_de") or "").strip()
        headers = properties.get("cot") or []
        label = "BẢNG:" if len(tables) == 1 else f"BẢNG {position}:"
        lines.append(label)
        if title:
            lines.append(_short_text(title))
        if headers:
            lines.append("Cột: " + " | ".join(str(header) for header in headers))

        table_rows = [
            row for row in rows
            if str(row["metadata"].get("table_node_id") or "") == table_id
        ]
        if table_rows:
            lines.append("DỮ LIỆU:")
            for row in table_rows:
                rendered_row = _row_text(row, headers)
                if rendered_row:
                    lines.append(f"- {rendered_row}")
    return lines


def _render_notification_bundle(
    position: int,
    seed: Candidate,
    expansions: list[Candidate],
) -> str:
    lines = [f"[NGUỒN {position}]", *_render_notification_header(seed)]
    provenance = seed["metadata"].get("provenance") or {}

    if seed["label"] == "Muc":
        lines.append(f"SEED — {_muc_label(seed['properties'])}:")
        lines.append(_muc_text(seed) or "(Mục không có nội dung văn bản)")
        lines.extend(_render_document_mucs(seed, expansions))
        if seed["metadata"].get("asks_list"):
            lines.extend(_render_muc_tables(expansions))
        return "\n".join(lines)

    if seed["label"] == "DongBang":
        table = provenance.get("bang") or {}

        table_title = str(table.get("tieu_de") or "").strip()
        if table_title:
            lines.append(f"Bảng: {_short_text(table_title)}")

        headers = table.get("cot") or seed["metadata"].get("table_headers") or []
        if headers:
            lines.append("Cột: " + " | ".join(str(header) for header in headers))

        lines.extend(["DÒNG SEED:", _row_text(seed, headers)])
        owner_muc_expansions = [
            item for item in expansions
            if item["source"] == "document_muc_expansion"
        ]
        lines.extend(
            _render_document_mucs(
                seed,
                owner_muc_expansions,
                heading="MỤC CHỨA BẢNG:",
            )
        )

        related_mucs = [
            item for item in expansions
            if item["source"] == "document_related_muc_expansion"
        ]
        if related_mucs:
            lines.append("MỤC LIÊN QUAN CÙNG TÀI LIỆU:")
            seen_related_mucs: set[str] = set()
            for section in related_mucs:
                identity = str(section["properties"].get("id") or section["node_id"])
                if identity in seen_related_mucs:
                    continue
                seen_related_mucs.add(identity)
                content = _muc_text(section)
                label = _muc_label(section["properties"])
                lines.append(
                    f"- {label}: {content}"
                    if content else f"- {label}"
                )

        related_rows = [
            item for item in expansions
            if item["source"] == "document_table_row_expansion"
        ]
        if related_rows:
            lines.append("CÁC DÒNG CÙNG GIÁ TRỊ EXACT:")
            for row in related_rows:
                rendered_row = _row_text(row, headers)
                if rendered_row:
                    lines.append(f"- {rendered_row}")

        return "\n".join(lines)


def _fit_notification_block(block: str, max_chars: int) -> str:
    """Giới hạn context tại ranh giới dòng, không cắt giữa một field bảng."""
    if len(block) <= max_chars:
        return block
    kept_lines: list[str] = []
    for line in block.splitlines():
        trial = "\n".join([*kept_lines, line])
        if len(trial) > max_chars:
            break
        kept_lines.append(line)
    marker = "[Context THONG_BAO đã được giới hạn]"
    trial = "\n".join([*kept_lines, marker])
    if len(trial) <= max_chars:
        kept_lines.append(marker)
    logger.warning(
        "[thong_bao][context] truncated original_chars=%s kept_chars=%s",
        len(block),
        len("\n".join(kept_lines)),
    )
    return "\n".join(kept_lines)


def build_context(candidates: Iterable[Candidate], max_chars: int = 12000) -> str:
    """Render ranked roots and their notification expansions into one LLM context."""
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero")
    materialized = list(candidates)
    roots = [item for item in materialized if item["source"] not in EXPANSION_SOURCES]
    if not roots:
        return "Không có dữ liệu tham khảo phù hợp."

    children: dict[tuple[str, str], list[Candidate]] = {
        (root["domain"], root["node_id"]): [] for root in roots
    }
    for item in materialized:
        if item["source"] not in EXPANSION_SOURCES:
            continue
        anchor = str(item["metadata"].get("anchor_node_id") or "")
        anchor_domain = str(item["metadata"].get("anchor_domain") or item["domain"])
        key = (anchor_domain, anchor)
        if key in children:
            children[key].append(item)

    blocks: list[str] = []
    for position, root in enumerate(roots, start=1):
        key = (root["domain"], root["node_id"])
        expansions = children[key]
        if root["domain"] == DOMAIN_THONG_BAO:
            block = _render_notification_bundle(position, root, expansions)
            current = "\n\n".join(blocks)
            separator_size = 2 if blocks else 0
            remaining = max_chars - len(current) - separator_size
            if remaining <= 0:
                break
            fitted_block = _fit_notification_block(block, remaining)
            if fitted_block:
                blocks.append(fitted_block)
            if fitted_block != block:
                break
            continue
        else:
            block_lines = [_render_root(position, root)]
            if expansions:
                block_lines.append("Mở rộng liên quan:")
                block_lines.extend(_render_expansion(item) for item in expansions)
            block = "\n".join(block_lines)
        trial = "\n\n".join([*blocks, block])
        if len(trial) > max_chars:
            remaining = max_chars - len("\n\n".join(blocks))
            if remaining > 0:
                blocks.append(block[:remaining])
            break
        blocks.append(block)
    return "\n\n".join(blocks)
