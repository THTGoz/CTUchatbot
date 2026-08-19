"""Document-aware evidence expansion for notification retrieval seeds."""

from __future__ import annotations

from collections.abc import Callable
from csv import reader
from typing import Any

from app.services.common.candidate import DOMAIN_THONG_BAO, Candidate, make_candidate
from app.services.thong_bao.retriever import (
    _danh_sach_exact,
    _gia_tri_khop_bat_ky,
    _loai_exact_cua_header,
    _tu_ban_ghi,
)
from app.services.thong_bao.utils import bo_dau


ReadQuery = Callable[[str, dict[str, Any]], list[dict[str, Any]]]

_LIST_SIGNALS = (
    "danh sach",
    "nhung ai",
    "ai duoc",
    "ai bi",
    "sinh vien nao",
    "nhung sinh vien nao",
    "cac sinh vien nao",
    "hoc phan nao",
    "nhung hoc phan nao",
    "cac hoc phan nao",
    "lop nao",
    "nhung lop nao",
    "cac lop nao",
    "cac truong hop nao",
)


def _resolve_reader(reader: ReadQuery | None) -> ReadQuery:
    """Dùng reader được truyền vào khi test, nếu không thì dùng Neo4j chung."""
    if reader is not None:
        return reader
    from app.db.neo4j import read_query

    return read_query


def asks_list(normalized_query: str) -> bool:
    """Nhận biết yêu cầu liệt kê bằng tín hiệu nhỏ, deterministic và không gọi LLM."""
    query = " ".join(bo_dau(normalized_query).split())
    return any(signal in query for signal in _LIST_SIGNALS)


def _anchor_metadata(seed: Candidate, **extra: Any) -> dict[str, Any]:
    return {
        "anchor_node_id": seed["node_id"],
        "anchor_domain": seed["domain"],
        **extra,
    }


def _build_exact_constraints(
    headers: list[Any],
    exact_columns: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Chỉ lấy các điều kiện exact có cột tương ứng trong Bang hiện tại."""
    constraints: dict[str, list[str]] = {}
    for header in headers:
        exact_type = _loai_exact_cua_header(str(header))
        if exact_type is None:
            continue
        exact_values = _danh_sach_exact(exact_columns.get(exact_type))
        if exact_values:
            constraints[exact_type] = exact_values
    return constraints


def _row_matches_constraints(
    headers: list[Any],
    values: list[Any],
    constraints: dict[str, list[str]],
) -> bool:
    """So khớp mọi exact value tại đúng vị trí cột của Bang."""
    for exact_type, exact_values in constraints.items():
        found_match = False
        for column_index, header in enumerate(headers):
            if _loai_exact_cua_header(str(header)) != exact_type:
                continue
            if column_index >= len(values):
                continue
            if _gia_tri_khop_bat_ky(
                exact_type,
                values[column_index],
                exact_values,
            ):
                found_match = True
                break
        if not found_match:
            return False
    return True


def load_seed_provenance(
    seed: Candidate,
    *,
    reader: ReadQuery | None = None,
) -> dict[str, Any]:
    """Tìm đúng TaiLieu tổ tiên và provenance của seed mà không tạo candidate phụ."""
    if seed["domain"] != DOMAIN_THONG_BAO:
        return {}

    if seed["label"] == "Muc":
        cypher = """
        MATCH (tb:ThongBao)-[:CO_TAI_LIEU]->(tl:TaiLieu)
        MATCH path=(tl)-[:CO_MUC*1..]->(seed:Muc)
        WHERE seed.id = $node_id
        OPTIONAL MATCH (parent:Muc)-[:CO_MUC]->(seed)
        RETURN tb{.id, .tieu_de, .nam_hoc, .hoc_ky} AS thong_bao,
               tl{.id, .thu_tu, .ten_tai_lieu} AS tai_lieu,
               CASE WHEN parent IS NULL THEN null
                    ELSE parent{.id, .ky_hieu, .noi_dung} END AS parent_muc,
               seed{.*, embedding: null} AS muc,
               length(path) AS seed_depth
        ORDER BY seed_depth
        LIMIT 1
        """
    elif seed["label"] == "DongBang":
        cypher = """
        MATCH (tb:ThongBao)-[:CO_TAI_LIEU]->(tl:TaiLieu)
        MATCH path=(tl)-[:CO_MUC*1..]->(m:Muc)-[:CO_BANG]->(b:Bang)
              -[:CO_DONG]->(seed:DongBang)
        WHERE seed.id = $node_id
        OPTIONAL MATCH (parent:Muc)-[:CO_MUC]->(m)
        RETURN tb{.id, .tieu_de, .nam_hoc, .hoc_ky} AS thong_bao,
               tl{.id, .thu_tu, .ten_tai_lieu} AS tai_lieu,
               CASE WHEN parent IS NULL THEN null
                    ELSE parent{.id, .ky_hieu, .noi_dung} END AS parent_muc,
               m{.*, embedding: null} AS muc,
               b{.id, .thu_tu, .tieu_de, .cot} AS bang,
               length(path) AS seed_depth
        ORDER BY seed_depth
        LIMIT 1
        """
    else:
        return {}

    rows = _resolve_reader(reader)(cypher, {"node_id": seed["node_id"]})
    provenance = dict(rows[0]) if rows else {}
    seed["metadata"]["provenance"] = provenance

    notice = provenance.get("thong_bao") or {}
    document = provenance.get("tai_lieu") or {}
    table = provenance.get("bang") or {}
    if notice:
        seed["metadata"].update({
            "notification_id": notice.get("id"),
            "ten_thong_bao": notice.get("tieu_de"),
            "nam_hoc": notice.get("nam_hoc"),
            "hoc_ky": notice.get("hoc_ky"),
        })
    if document:
        seed["metadata"]["tai_lieu_id"] = document.get("id")
    if table:
        seed["metadata"].update({
            "parent_table_id": table.get("id"),
            "table_headers": table.get("cot") or [],
        })
    return provenance


def _load_document_tables(
    seed: Candidate,
    tai_lieu_id: str,
    query_vector: list[float],
    *,
    reader: ReadQuery | None = None,
) -> list[dict[str, Any]]:
    """Đọc metadata bảng cùng TaiLieu và dùng vector đã có để xếp bảng gián tiếp."""
    score_expression = (
        "max(CASE WHEN row.embedding IS NULL THEN null "
        "ELSE vector.similarity.cosine(row.embedding, $query_vector) END)"
        if query_vector
        else "null"
    )
    cypher = f"""
    MATCH path=(tl:TaiLieu {{id: $tai_lieu_id}})-[:CO_MUC*1..]->(owner:Muc)
          -[:CO_BANG]->(b:Bang)
    OPTIONAL MATCH (b)-[:CO_DONG]->(row:DongBang)
    RETURN owner.id AS owner_node_id,
           b.id AS table_node_id,
           b{{.*}} AS table_properties,
           b.thu_tu AS table_order,
           b.id AS table_id,
           owner.id = $seed_node_id AS direct_to_seed,
           [node IN nodes(path) | coalesce(node.id, '')] AS document_path,
           {score_expression} AS table_score
    ORDER BY direct_to_seed DESC, table_score DESC, document_path, table_order, table_id
    """
    return _resolve_reader(reader)(
        cypher,
        {
            "tai_lieu_id": tai_lieu_id,
            "seed_node_id": seed["node_id"],
            "query_vector": query_vector,
        },
    )


def _select_relevant_tables(
    seed: Candidate,
    table_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ưu tiên bảng trực tiếp của Muc; nếu không có thì lấy bảng semantic tốt nhất."""
    exact_columns = seed["metadata"].get("exact_columns") or {}
    eligible: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in table_rows:
        table_id = str(item.get("table_node_id") or "")
        if not table_id or table_id in seen:
            continue
        headers = (item.get("table_properties") or {}).get("cot") or []
        constraints = _build_exact_constraints(headers, exact_columns)
        # Có exact value thì bảng phải có ít nhất một cột tương ứng mới phù hợp.
        if exact_columns and not constraints:
            continue
        seen.add(table_id)
        eligible.append(item)

    direct_tables = [item for item in eligible if item.get("direct_to_seed")]
    if direct_tables:
        return direct_tables
    if not eligible:
        return []

    def semantic_score(item: dict[str, Any]) -> float:
        try:
            return float(item.get("table_score"))
        except (TypeError, ValueError):
            return float("-inf")

    return [max(eligible, key=semantic_score)]


def _load_selected_table_rows(
    table_node_ids: list[str],
    *,
    reader: ReadQuery | None = None,
) -> list[dict[str, Any]]:
    """Đọc dòng của các bảng đã chọn theo đúng DongBang.thu_tu."""
    if not table_node_ids:
        return []
    return _resolve_reader(reader)(
        """
        MATCH (b:Bang)-[:CO_DONG]->(d:DongBang)
        WHERE b.id IN $table_node_ids
        RETURN b.id AS table_node_id,
               d.id AS row_node_id,
               d{.*, embedding: null} AS row_properties
        ORDER BY b.thu_tu, b.id, d.thu_tu
        """,
        {"table_node_ids": table_node_ids},
    )


def expand_muc_list_tables(
    seed: Candidate,
    tai_lieu_id: str,
    query_vector: list[float],
    *,
    reader: ReadQuery | None = None,
) -> list[Candidate]:
    """Chỉ khi hỏi list, chọn Bang trong TaiLieu rồi lấy các dòng đúng thứ tự."""
    available_tables = _load_document_tables(
        seed,
        tai_lieu_id,
        query_vector,
        reader=reader,
    )
    selected_tables = _select_relevant_tables(seed, available_tables)
    table_ids = [str(item.get("table_node_id") or "") for item in selected_tables]
    row_records = _load_selected_table_rows(table_ids, reader=reader)
    rows_by_table: dict[str, list[dict[str, Any]]] = {table_id: [] for table_id in table_ids}
    for row in row_records:
        table_id = str(row.get("table_node_id") or "")
        if table_id in rows_by_table:
            rows_by_table[table_id].append(row)

    exact_columns = seed["metadata"].get("exact_columns") or {}
    result: list[Candidate] = []
    for item in selected_tables:
        table_node_id = str(item.get("table_node_id") or "")
        table_properties = dict(item.get("table_properties") or {})
        headers = table_properties.get("cot") or []
        constraints = _build_exact_constraints(headers, exact_columns)
        matching_rows = [
            row
            for row in rows_by_table.get(table_node_id, [])
            if not constraints
            or _row_matches_constraints(
                headers,
                (row.get("row_properties") or {}).get("gia_tri") or [],
                constraints,
            )
        ]
        if constraints and not matching_rows:
            continue

        result.append(make_candidate(
            node_id=table_node_id,
            label="Bang",
            cosine_score=0.0,
            properties=table_properties,
            source="document_table_expansion",
            domain=DOMAIN_THONG_BAO,
            metadata=_anchor_metadata(
                seed,
                tai_lieu_id=tai_lieu_id,
                parent_table_id=table_properties.get("id"),
                table_headers=headers,
                direct_to_seed=bool(item.get("direct_to_seed")),
                table_score=item.get("table_score"),
            ),
        ))
        for row in matching_rows:
            result.append(make_candidate(
                node_id=row.get("row_node_id"),
                label="DongBang",
                cosine_score=0.0,
                properties=row.get("row_properties"),
                source="document_table_row_expansion",
                domain=DOMAIN_THONG_BAO,
                metadata=_anchor_metadata(
                    seed,
                    tai_lieu_id=tai_lieu_id,
                    parent_table_id=table_properties.get("id"),
                    table_node_id=table_node_id,
                    table_headers=headers,
                    exact_columns=constraints,
                ),
            ))
    return result


def expand_same_table_rows(
    seed: Candidate,
    *,
    reader: ReadQuery | None = None,
) -> list[Candidate]:
    """Với DongBang list seed, lấy dòng cùng Bang và lọc exact tại đúng cột."""
    if seed["label"] != "DongBang":
        return []
    table_id = str(seed["metadata"].get("parent_table_id") or "")
    notification_id = str(seed["metadata"].get("notification_id") or "")
    exact_columns = seed["metadata"].get("exact_columns") or {}
    headers = seed["metadata"].get("table_headers") or []
    if not table_id or not headers:
        return []

    constraints = _build_exact_constraints(headers, exact_columns)
    if exact_columns and not constraints:
        return []

    rows = _resolve_reader(reader)(
        """
        MATCH (tb:ThongBao)-[:CO_TAI_LIEU]->(:TaiLieu)
              -[:CO_MUC*1..]->(:Muc)-[:CO_BANG]->(b:Bang {id: $table_id})
              -[:CO_DONG]->(d:DongBang)
        WHERE $notification_id = '' OR tb.id = $notification_id
        RETURN d.id AS node_id, 'DongBang' AS label,
               0.0 AS score, d{.*, embedding: null} AS properties,
               tb.id AS notification_id, tb.nam_hoc AS nam_hoc,
               tb.hoc_ky AS hoc_ky, tb.tieu_de AS ten_thong_bao,
               b.id AS parent_table_id, b.cot AS table_headers
        ORDER BY d.thu_tu
        """,
        {"table_id": table_id, "notification_id": notification_id},
    )
    result: list[Candidate] = []
    for item in rows:
        if str(item.get("node_id") or "") == seed["node_id"]:
            continue
        values = (item.get("properties") or {}).get("gia_tri") or []
        if constraints and not _row_matches_constraints(headers, values, constraints):
            continue
        expanded = _tu_ban_ghi(
            item,
            source="document_table_row_expansion",
            exact_columns=constraints,
        )
        expanded["metadata"].update(_anchor_metadata(
            seed,
            tai_lieu_id=seed["metadata"].get("tai_lieu_id"),
            table_node_id=seed["metadata"].get("provenance", {}).get("bang", {}).get("id"),
        ))
        result.append(expanded)
    return result


def expand_owner_muc(
    seed: Candidate,
    provenance: dict[str, Any],
) -> list[Candidate]:
    """Với DongBang seed, luôn thêm Muc trực tiếp chứa Bang vào evidence."""
    if seed["label"] != "DongBang":
        return []

    owner_muc = dict(provenance.get("muc") or {})
    owner_id = str(owner_muc.get("id") or "")
    if not owner_id:
        return []

    return [make_candidate(
        node_id=owner_id,
        label="Muc",
        cosine_score=0.0,
        properties=owner_muc,
        source="document_muc_expansion",
        domain=DOMAIN_THONG_BAO,
        metadata=_anchor_metadata(
            seed,
            tai_lieu_id=seed["metadata"].get("tai_lieu_id"),
            parent_table_id=seed["metadata"].get("parent_table_id"),
        ),
    )]


def expand_related_mucs_same_document(
    seed: Candidate,
    tai_lieu_id: str,
    query_vector: list[float],
    provenance: dict[str, Any],
    *,
    top_k: int = 2,
    reader: ReadQuery | None = None,
) -> list[Candidate]:
    """
    Với exact DongBang seed, lấy thêm các Muc ngữ nghĩa phù hợp trong cùng TaiLieu.

    Exact giúp xác định đúng dòng/bảng/tài liệu, còn bước này bổ sung phần văn bản
    có thể chứa hướng dẫn hoặc giải thích mà DongBang không thể hiện đầy đủ.
    Chỉ lấy top-k để tránh kéo toàn bộ tài liệu vào context.
    """
    if seed["label"] != "DongBang" or not query_vector or top_k <= 0:
        return []

    owner_muc = provenance.get("muc") or {}
    owner_muc_id = str(owner_muc.get("id") or "")

    rows = _resolve_reader(reader)(
        """
        MATCH (tb:ThongBao)-[:CO_TAI_LIEU]->(tl:TaiLieu {id: $tai_lieu_id})
        MATCH (tl)-[:CO_MUC*1..]->(m:Muc)
        WHERE m.id <> $owner_muc_id
          AND m.embedding IS NOT NULL
        WITH tb, m, vector.similarity.cosine(m.embedding, $query_vector) AS score
        WHERE score IS NOT NULL
        RETURN m.id AS node_id,
               score,
               m{.*, embedding: null} AS properties,
               tb.id AS notification_id,
               tb.tieu_de AS ten_thong_bao,
               tb.nam_hoc AS nam_hoc,
               tb.hoc_ky AS hoc_ky
        ORDER BY score DESC, node_id
        LIMIT $top_k
        """,
        {
            "tai_lieu_id": tai_lieu_id,
            "owner_muc_id": owner_muc_id,
            "query_vector": query_vector,
            "top_k": top_k,
        },
    )

    result: list[Candidate] = []
    for item in rows:
        result.append(make_candidate(
            node_id=item.get("node_id"),
            label="Muc",
            cosine_score=item.get("score"),
            properties=item.get("properties"),
            source="document_related_muc_expansion",
            domain=DOMAIN_THONG_BAO,
            metadata=_anchor_metadata(
                seed,
                tai_lieu_id=tai_lieu_id,
                notification_id=item.get("notification_id"),
                ten_thong_bao=item.get("ten_thong_bao"),
                nam_hoc=item.get("nam_hoc"),
                hoc_ky=item.get("hoc_ky"),
            ),
        ))
    return result


def expand_notification_candidate(
    seed: Candidate,
    list_requested: bool,
    query_vector: list[float],
    *,
    reader: ReadQuery | None = None,
) -> list[Candidate]:
    """DongBang luôn lấy Muc chứa nó; expansion bảng khác vẫn theo logic hiện có."""
    if seed["domain"] != DOMAIN_THONG_BAO:
        return []

    provenance = load_seed_provenance(seed, reader=reader)
    document = provenance.get("tai_lieu") or {}
    tai_lieu_id = str(document.get("id") or "")
    seed["metadata"]["asks_list"] = list_requested
    if not tai_lieu_id:
        return []

    # Không mở rộng các Mục/Mục con khác chỉ vì cùng TaiLieu.
    # Riêng DongBang luôn lấy Muc trực tiếp chứa Bang để bổ sung ngữ cảnh.
    evidence: list[Candidate] = []
    if seed["label"] == "DongBang":
        evidence.extend(expand_owner_muc(seed, provenance))

    # DongBang được lấy bằng exact:
    # 1) mở lại tất cả dòng cùng bảng thỏa cùng giá trị exact;
    # 2) lấy thêm một số Muc ngữ nghĩa phù hợp trong đúng TaiLieu đã được exact neo lại.
    if (
        seed["label"] == "DongBang"
        and seed["metadata"].get("exact_columns")
    ):
        evidence.extend(
            expand_same_table_rows(seed, reader=reader)
        )
        evidence.extend(
            expand_related_mucs_same_document(
                seed,
                tai_lieu_id,
                query_vector,
                provenance,
                top_k=2,
                reader=reader,
            )
        )
        return evidence

    # Những expansion còn lại chỉ áp dụng khi câu hỏi yêu cầu danh sách.
    if not list_requested:
        return evidence

    if seed["label"] == "Muc":
        evidence.extend(
            expand_muc_list_tables(
                seed,
                tai_lieu_id,
                query_vector,
                reader=reader,
            )
        )
    elif seed["label"] == "DongBang":
        evidence.extend(
            expand_same_table_rows(seed, reader=reader)
        )

    return evidence
