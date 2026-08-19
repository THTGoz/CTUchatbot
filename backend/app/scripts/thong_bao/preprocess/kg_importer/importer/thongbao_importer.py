from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neo4j import ManagedTransaction

from .tailieu_importer import import_tailieu_list
from ..utils.id_utils import thongbao_id_from_filename
from ..utils.metadata_utils import build_notice_metadata


# Import một thông báo gốc cùng toàn bộ cây tài liệu bên dưới.
def import_thongbao(
    tx: ManagedTransaction,
    data: dict[str, Any],
) -> dict[str, int]:
    metadata = data.get("metadata", {})
    documents = data.get("tai_lieu", [])
    if not isinstance(metadata, dict) or not isinstance(documents, list):
        raise TypeError("JSON phải có metadata object và tai_lieu list.")

    filename = str(metadata.get("ten_file", "")).strip()
    title = str(metadata.get("tieu_de", "")).strip()
    issue_date = str(metadata.get("ngay_ban_hanh", "")).strip()
    node_id = thongbao_id_from_filename(filename)
    notice_metadata = build_notice_metadata(
        filename=filename,
        title=title,
        issue_date=issue_date,
        source_metadata=metadata,
    )

    properties: dict[str, Any] = {
        "id": node_id,
        "ten_file": filename,
        "tieu_de": title,
        **notice_metadata,
    }

    tx.run("CREATE (notice:ThongBao) SET notice = $properties", properties=properties).consume()

    counts: Counter[str] = Counter({"ThongBao": 1})
    import_tailieu_list(
        tx,
        thongbao_id=node_id,
        documents=documents,
        ten_thong_bao=title,
        counts=counts,
    )
    return dict(counts)
