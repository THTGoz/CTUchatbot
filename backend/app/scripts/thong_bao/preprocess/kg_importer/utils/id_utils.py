from __future__ import annotations


def thongbao_id_from_filename(filename: str) -> str:
    value = str(filename).strip()
    if value.casefold().endswith(".pdf"):
        value = value[:-4]
    if not value:
        raise ValueError("Không thể tạo ThongBao.id từ tên file rỗng.")
    return value


def child_id(thongbao_id: str, json_id: str) -> str:
    value = str(json_id).strip()
    if not value:
        raise ValueError("Node con thiếu id trong JSON.")
    return f"{thongbao_id}_{value}"


def bang_id(muc_id: str, table_index: int) -> str:
    return f"{muc_id}_bang_{table_index}"


def dongbang_id(table_id: str, row_index: int) -> str:
    return f"{table_id}_dong_{row_index}"
