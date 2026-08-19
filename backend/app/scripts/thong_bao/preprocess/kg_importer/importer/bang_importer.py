from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neo4j import ManagedTransaction

from .dongbang_importer import import_dongbang_rows
from ..utils.id_utils import bang_id
from ..utils.text_utils import forward_fill_rows


# Import danh sách bảng thuộc một mục và tiếp tục import từng dòng bảng.
def import_bang_list(
    tx: ManagedTransaction,
    *,
    muc_id: str,
    tables: list[dict[str, Any]],
    ten_thong_bao: str,
    context: list[str],
    counts: Counter[str],
) -> None:
    query = """
    MATCH (section:Muc {id: $muc_id})
    CREATE (table:Bang)
    SET table = $properties
    CREATE (section)-[:CO_BANG]->(table)
    """

    for table_index, table in enumerate(tables, start=1):
        if not isinstance(table, dict):
            raise TypeError(f"Bảng {table_index} của mục {muc_id} phải là object.")

        columns = table.get("cot", [])
        rows = table.get("du_lieu", [])
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise TypeError(f"Bảng {table_index} của mục {muc_id} sai schema.")
        for row_index, row in enumerate(rows, start=1):
            if not isinstance(row, list):
                raise TypeError(
                    f"Dòng {row_index} của bảng {table_index} "
                    f"thuộc mục {muc_id} phải là list."
                )

        columns = [str(column).strip() for column in columns]
        filled_rows = forward_fill_rows(columns, rows)
        title = str(table.get("tieu_de_bang", "")).strip()
        node_id = bang_id(muc_id, table_index)
        properties = {
            "id": node_id,
            "thu_tu": table_index,
            "tieu_de": title,
            "cot": columns,
        }
        tx.run(query, muc_id=muc_id, properties=properties).consume()
        counts["Bang"] += 1

        import_dongbang_rows(
            tx,
            table_id=node_id,
            columns=columns,
            filled_rows=filled_rows,
            ten_thong_bao=ten_thong_bao,
            context=context,
            tieu_de_bang=title,
            counts=counts,
        )
