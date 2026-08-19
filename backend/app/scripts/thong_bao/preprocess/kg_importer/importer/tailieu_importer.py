from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neo4j import ManagedTransaction

from .muc_importer import import_muc_list
from ..utils.id_utils import child_id


# Import danh sách tài liệu con của một thông báo.
def import_tailieu_list(
    tx: ManagedTransaction,
    *,
    thongbao_id: str,
    documents: list[dict[str, Any]],
    ten_thong_bao: str,
    counts: Counter[str],
) -> None:
    query = """
    MATCH (notice:ThongBao {id: $thongbao_id})
    CREATE (document:TaiLieu)
    SET document = $properties
    CREATE (notice)-[:CO_TAI_LIEU]->(document)
    """

    for document in documents:
        if not isinstance(document, dict):
            raise TypeError("Mỗi phần tử tai_lieu phải là object.")

        json_id = str(document.get("id", "")).strip()
        node_id = child_id(thongbao_id, json_id)
        order = int(document.get("thu_tu", 0))
        document_title = str(document.get("ten_tai_lieu", "")).strip()
        if not document_title:
            raise ValueError(f"Tài liệu {json_id} thiếu ten_tai_lieu từ pipeline JSON.")
        sections = document.get("muc", [])
        if not isinstance(sections, list):
            raise TypeError(f"Tài liệu {json_id} có trường muc không phải list.")

        properties = {
            "id": node_id,
            "thu_tu": order,
            "ten_tai_lieu": document_title,
        }
        tx.run(query, thongbao_id=thongbao_id, properties=properties).consume()
        counts["TaiLieu"] += 1

        import_muc_list(
            tx,
            thongbao_id=thongbao_id,
            parent_label="TaiLieu",
            parent_id=node_id,
            sections=sections,
            ten_thong_bao=ten_thong_bao,
            parent_context=[],
            counts=counts,
        )
