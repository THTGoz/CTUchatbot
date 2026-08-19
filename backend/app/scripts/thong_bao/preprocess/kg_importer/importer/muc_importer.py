from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from neo4j import ManagedTransaction

from .bang_importer import import_bang_list
from ..utils.id_utils import child_id
from ..utils.text_utils import build_muc_text


ParentLabel = Literal["TaiLieu", "Muc"]


# Ghép các đoạn nội dung không rỗng của một mục.
def join_content(content: list[Any]) -> str:
    return "\n\n".join(
        value for value in (str(item).strip() for item in content) if value
    )


# Tạo nhãn hiển thị cho mục có hoặc không có ký hiệu.
def section_label(symbol: str) -> str:
    return f"Mục {symbol}" if symbol else "Mở đầu"


# Import đệ quy danh sách mục, bảng và mục con.
def import_muc_list(
    tx: ManagedTransaction,
    *,
    thongbao_id: str,
    parent_label: ParentLabel,
    parent_id: str,
    sections: list[dict[str, Any]],
    ten_thong_bao: str,
    parent_context: list[str],
    counts: Counter[str],
) -> None:
    relation_query = {
        "TaiLieu": """
            MATCH (parent:TaiLieu {id: $parent_id})
            CREATE (section:Muc)
            SET section = $properties
            CREATE (parent)-[:CO_MUC]->(section)
        """,
        "Muc": """
            MATCH (parent:Muc {id: $parent_id})
            CREATE (section:Muc)
            SET section = $properties
            CREATE (parent)-[:CO_MUC]->(section)
        """,
    }[parent_label]

    for section in sections:
        if not isinstance(section, dict):
            raise TypeError(f"Mục con của {parent_id} phải là object.")

        json_id = str(section.get("id", "")).strip()
        node_id = child_id(thongbao_id, json_id)
        symbol = str(section.get("ky_hieu", "")).strip()

        raw_content = section.get("noi_dung", [])
        tables = section.get("bang", [])
        children = section.get("muc_con", [])
        if not all(isinstance(value, list) for value in (raw_content, tables, children)):
            raise TypeError(f"Mục {json_id} sai schema list.")

        content = join_content(raw_content)
        properties = {
            "id": node_id,
            "ky_hieu": symbol,
            "noi_dung": content,
            "text": build_muc_text(ten_thong_bao, parent_context, content),
        }
        tx.run(relation_query, parent_id=parent_id, properties=properties).consume()
        counts["Muc"] += 1

        current_heading = (
            str(raw_content[0]).strip() if raw_content else section_label(symbol)
        )
        current_context = [*parent_context, current_heading]

        import_bang_list(
            tx,
            muc_id=node_id,
            tables=tables,
            ten_thong_bao=ten_thong_bao,
            context=current_context,
            counts=counts,
        )

        import_muc_list(
            tx,
            thongbao_id=thongbao_id,
            parent_label="Muc",
            parent_id=node_id,
            sections=children,
            ten_thong_bao=ten_thong_bao,
            parent_context=current_context,
            counts=counts,
        )
