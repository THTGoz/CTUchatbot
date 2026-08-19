from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neo4j import ManagedTransaction

from ..utils.id_utils import dongbang_id
from ..utils.text_utils import build_dongbang_noi_dung, build_dongbang_text


# Import các dòng đã forward-fill vào một node bảng.
def import_dongbang_rows(
    tx: ManagedTransaction,
    *,
    table_id: str,
    columns: list[str],
    filled_rows: list[list[str]],
    ten_thong_bao: str,
    context: list[str],
    tieu_de_bang: str,
    counts: Counter[str],
) -> None:
    query = """
    MATCH (table:Bang {id: $table_id})
    CREATE (row:DongBang)
    SET row = $properties
    CREATE (table)-[:CO_DONG]->(row)
    """

    for row_index, filled_row in enumerate(filled_rows, start=1):
        properties: dict[str, Any] = {
            "id": dongbang_id(table_id, row_index),
            "thu_tu": row_index,
            "text": build_dongbang_text(
                ten_thong_bao,
                context,
                tieu_de_bang,
                columns,
                filled_row,
            ),
            "noi_dung_dong": build_dongbang_noi_dung(columns, filled_row),
            "gia_tri": filled_row,
        }
        tx.run(query, table_id=table_id, properties=properties).consume()
        counts["DongBang"] += 1
