"""Document-aware evidence expansion for notification retrieval seeds."""

from __future__ import annotations

from collections.abc import Callable
from csv import reader
from typing import Any

from app.services.common.candidate import DOMAIN_THONG_BAO, Candidate, make_candidate
from app.services.thong_bao.retriever import (
    _gia_tri_khop,
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
    exact_columns: dict[str, str],
) -> dict[str, str]:
    """Chỉ lấy các điều kiện exact có cột tương ứng trong Bang hiện tại."""
    constraints: dict[str, str] = {}
    for header in headers:
        exact_type = _loai_exact_cua_header(str(header))
        if exact_type is None:
            continue
        exact_value = exact_columns.get(exact_type)
        if exact_value is not None:
            constraints[exact_type] = exact_value
    return constraints


def _row_matches_constraints(
    headers: list[Any],
    values: list[Any],
    constraints: dict[str, str],
) -> bool:
    """So khớp mọi exact value tại đúng vị trí cột của Bang."""
    for exact_type, exact_value in constraints.items():
        found_match = False
        for column_index, header in enumerate(headers):
            if _loai_exact_cua_header(str(header)) != exact_type:
                continue
            if column_index >= len(values):
                continue
            if _gia_tri_khop(exact_type, values[column_index], exact_value):
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
        seed["metadata"]["parent_table_id"] = table.get("id")
        seed["metadata"]["table_headers"] = table.get("cot") or []
    return provenance


def _order_mucs_within_tailieu(
    mucs: list[dict[str, Any]],
    *,
    tai_lieu_id: str,
    reader: ReadQuery | None = None,
) -> list[dict[str, Any]]:
    """Giữ thứ tự duyệt DFS của cây Mục trong TaiLieu."""
    if len(mucs) <= 1:
        return mucs

    muc_ids = [str(item["id"]) for item in mucs if item.get("id")]
    order_rows = _resolve_reader(reader)(
        """
        MATCH (tl:TaiLieu {id: $tai_lieu_id})
        MATCH path=(tl)-[:CO_MUC*1..]->(m:Muc)
        WHERE m.id IN $muc_ids
        RETURN m.id AS id,
               [node IN nodes(path)[1..] | coalesce(node.thu_tu, 0)] AS sort_key
        """,
        {"tai_lieu_id": tai_lieu_id, "muc_ids": muc_ids},
    )
    sort_keys = {
        str(row["id"]): list(row.get("sort_key") or [])
        for row in order_rows
    }
    return sorted(
        mucs,
        key=lambda item: (sort_keys.get(str(item.get("id")), []), str(item.get("id"))),
    )


def expand_same_table_rows(
    seed: Candidate,
    *,
    reader: ReadQuery | None = None,
) -> list[Candidate]:
    """Mở rộng các DongBang khác trong cùng bảng có cùng giá trị exact."""
    if seed["label"] != "DongBang":
        return []

    parent_table_id = str(seed["metadata"].get("parent_table_id") or "")
    if not parent_table_id:
        return []

    exact_columns = seed["metadata"].get("exact_columns") or {}
    rows = _resolve_reader(reader)(
        """
        MATCH (tb:ThongBao)-[:CO_TAI_LIEU]->(:TaiLieu)-[:CO_MUC*1..]->(:Muc)
              -[:CO_BANG]->(b:Bang {id: $table_id})-[:CO_DONG]->(d:DongBang)
        WHERE d.id <> $node_id
        RETURN d.id AS node_id,
               d{.*, embedding: null} AS properties,
               b.cot AS table_headers,
               tb.id AS notification_id,
               tb.tieu_de AS ten_thong_bao,
               tb.nam_hoc AS nam_hoc,
               tb.hoc_ky AS hoc_ky
        ORDER BY d.thu_tu, d.id
        """,
        {"table_id": parent_table_id, "node_id": seed["node_id"]},
    )
    if not rows:
        return []

    headers = seed["metadata"].get("table_headers") or rows[0].get("table_headers") or []
    constraints = _build_exact_constraints(headers, exact_columns)
    matching_items = [
        item for item in rows
        if _row_matches_constraints(
            headers,
            (item.get("properties") or {}).get("gia_tri") or [],
            constraints,
        )
    ]
    result: list[Candidate] = []
    for item in matching_items:
        result.append(make_candidate(
            node_id=item.get("node_id"),
            label="DongBang",
            cosine_score=0.0,
            properties=item.get("properties"),
            source="document_table_row_expansion",
            domain=DOMAIN_THONG_BAO,
            metadata=_anchor_metadata(
                seed,
                parent_table_id=parent_table_id,
                table_node_id=parent_table_id,
                table_headers=headers,
                notification_id=item.get("notification_id"),
                ten_thong_bao=item.get("ten_thong_bao"),
                nam_hoc=item.get("nam_hoc"),
                hoc_ky=item.get("hoc_ky"),
            ),
        ))
    return result


def expand_muc_list_tables(
    seed: Candidate,
    tai_lieu_id: str,
    query_vector: list[float],
    *,
    reader: ReadQuery | None = None,
) -> list[Candidate]:
    """Mở rộng bảng và các dòng liên quan khi seed Muc nhận diện yêu cầu danh sách."""
    if seed["label"] != "Muc":
        return []

    raw_reader = _resolve_reader(reader)
    direct_tables = raw_reader(
        """
        MATCH (tb:ThongBao)-[:CO_TAI_LIEU]->(:TaiLieu)-[:CO_MUC*1..]->(m:Muc {id: $node_id})
              -[:CO_BANG]->(b:Bang)
        RETURN b.id AS id, b.thu_tu AS thu_tu, b.tieu_de AS tieu_de, b.cot AS cot,
               tb.id AS notification_id, tb.tieu_de AS ten_thong_bao,
               tb.nam_hoc AS nam_hoc, tb.hoc_ky AS hoc_ky
        ORDER BY b.thu_tu, b.id
        """,
        {"node_id": seed["node_id"]},
    )
    candidate_tables = direct_tables
    if not candidate_tables and tai_lieu_id and query_vector:
        candidate_tables = raw_reader(
            """
            MATCH (tb:ThongBao)-[:CO_TAI_LIEU]->(tl:TaiLieu {id: $tai_lieu_id})
                  -[:CO_MUC*1..]->(:Muc)-[:CO_BANG]->(b:Bang)-[:CO_DONG]->(d:DongBang)
            WHERE d.embedding IS NOT NULL
            WITH tb, b, d, vector.similarity.cosine(d.embedding, $query_vector) AS score
            ORDER BY score DESC, d.id
            WITH tb, b, max(score) AS max_score
            ORDER BY max_score DESC, b.id
            LIMIT 1
            RETURN b.id AS id, b.thu_tu AS thu_tu, b.tieu_de AS tieu_de, b.cot AS cot,
                   tb.id AS notification_id, tb.tieu_de AS ten_thong_bao,
                   tb.nam_hoc AS nam_hoc, tb.hoc_ky AS hoc_ky
            """,
            {"tai_lieu_id": tai_lieu_id, "query_vector": query_vector},
        )
    if not candidate_tables:
        return []

    chosen_table = candidate_tables[0]
    table_id = str(chosen_table["id"])
    headers = chosen_table.get("cot") or []

    rows = raw_reader(
        """
        MATCH (b:Bang {id: $table_id})-[:CO_DONG]->(d:DongBang)
        RETURN d.id AS node_id, d{.*, embedding: null} AS properties
        ORDER BY d.thu_tu, d.id
        """,
        {"table_id": table_id},
    )

    exact_columns = seed["metadata"].get("exact_columns") or {}
    constraints = _build_exact_constraints(headers, exact_columns)
    matching_rows = [
        item for item in rows
        if _row_matches_constraints(
            headers,
            (item.get("properties") or {}).get("gia_tri") or [],
            constraints,
        )
    ]

    result: list[Candidate] = [make_candidate(
        node_id=table_id,
        label="Bang",
        cosine_score=0.0,
        properties={
            "id": table_id,
            "thu_tu": chosen_table.get("thu_tu"),
            "tieu_de": chosen_table.get("tieu_de"),
            "cot": headers,
        },
        source="document_table_expansion",
        domain=DOMAIN_THONG_BAO,
        metadata=_anchor_metadata(
            seed,
            tai_lieu_id=tai_lieu_id,
            table_headers=headers,
            notification_id=chosen_table.get("notification_id"),
            ten_thong_bao=chosen_table.get("ten_thong_bao"),
            nam_hoc=chosen_table.get("nam_hoc"),
            hoc_ky=chosen_table.get("hoc_ky"),
        ),
    )]
    for item in matching_rows:
        result.append(make_candidate(
            node_id=item.get("node_id"),
            label="DongBang",
            cosine_score=0.0,
            properties=item.get("properties"),
            source="document_table_row_expansion",
            domain=DOMAIN_THONG_BAO,
            metadata=_anchor_metadata(
                seed,
                tai_lieu_id=tai_lieu_id,
                table_node_id=table_id,
                table_headers=headers,
                notification_id=chosen_table.get("notification_id"),
                ten_thong_bao=chosen_table.get("ten_thong_bao"),
                nam_hoc=chosen_table.get("nam_hoc"),
                hoc_ky=chosen_table.get("hoc_ky"),
            ),
        ))
    return result


def expand_owner_muc(
    seed: Candidate,
    provenance: dict[str, Any],
) -> list[Candidate]:
    """DongBang luôn lấy Muc trực tiếp chứa nó để bổ sung ngữ cảnh."""
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
