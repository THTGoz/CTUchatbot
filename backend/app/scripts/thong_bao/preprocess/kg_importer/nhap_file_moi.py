from __future__ import annotations

r"""Thêm một file ``*_chunks.json`` mới và embedding vào KG, không xóa dữ liệu cũ.

Ví dụ:
    python nhap_file_moi.py D:\du_lieu\thong_bao_chunks.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


from .config import load_settings
from .embedding.generate_embedding import NODE_LABELS, save_embeddings
from .importer.thongbao_importer import import_thongbao
from .neo4j_connection import Neo4jConnection
from .utils.id_utils import thongbao_id_from_filename


# Hiển thị tiếng Việt ổn định trên console Windows.
def cau_hinh_console_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


# Đọc một file chunks và kiểm tra cấu trúc tối thiểu trước khi kết nối Neo4j.
def doc_file_chunks(duong_dan: Path) -> dict[str, Any]:
    duong_dan = duong_dan.expanduser().resolve()
    if not duong_dan.is_file():
        raise FileNotFoundError(f"Không tìm thấy file: {duong_dan}")
    if not duong_dan.name.casefold().endswith("_chunks.json"):
        raise ValueError("File đầu vào phải có hậu tố _chunks.json.")

    with duong_dan.open("r", encoding="utf-8") as tep:
        du_lieu = json.load(tep)

    if not isinstance(du_lieu, dict):
        raise TypeError("JSON gốc phải là object.")
    if not isinstance(du_lieu.get("metadata"), dict):
        raise TypeError("JSON phải có metadata object.")
    if not isinstance(du_lieu.get("tai_lieu"), list):
        raise TypeError("JSON phải có tai_lieu list.")
    return du_lieu


# Lấy ID ThongBao bằng cùng quy tắc với importer chính.
def lay_id_thong_bao(du_lieu: dict[str, Any]) -> str:
    metadata = du_lieu["metadata"]
    return thongbao_id_from_filename(str(metadata.get("ten_file") or ""))


# Chỉ thêm khi ID chưa có; mọi lỗi đều rollback toàn bộ file đang nhập.
def them_thong_bao_moi(
    tx: Any,
    du_lieu: dict[str, Any],
    id_thong_bao: str,
) -> dict[str, int]:
    ban_ghi = tx.run(
        "MATCH (tb:ThongBao {id: $id}) RETURN tb.id AS id LIMIT 1",
        id=id_thong_bao,
    ).single()
    if ban_ghi is not None:
        raise ValueError(
            f"ThongBao '{id_thong_bao}' đã tồn tại; không có dữ liệu nào được thay đổi."
        )
    return import_thongbao(tx, du_lieu)


# Lấy các node thuộc đúng cây ThongBao vừa tạo để sinh embedding.
def lay_node_trong_cay(
    tx: Any,
    nhan: str,
    id_thong_bao: str,
) -> list[dict[str, str]]:
    if nhan not in NODE_LABELS:
        raise ValueError(f"Nhãn embedding không hợp lệ: {nhan}")
    truy_van = f"""
    MATCH (tb:ThongBao {{id: $id}})-[
        :CO_TAI_LIEU|CO_MUC|CO_BANG|CO_DONG*1..
    ]->(n:{nhan})
    WHERE n.text IS NOT NULL AND trim(n.text) <> ''
    RETURN DISTINCT n.id AS id, n.text AS text
    ORDER BY n.id
    """
    return [dict(ban_ghi) for ban_ghi in tx.run(truy_van, id=id_thong_bao)]


# Sinh và ghi embedding cho các node mới ngay trong transaction import.
def tao_embedding_trong_transaction(
    tx: Any,
    id_thong_bao: str,
    model: Any,
    kich_thuoc_batch: int,
) -> dict[str, int]:
    ket_qua: dict[str, int] = {}
    for nhan in NODE_LABELS:
        cac_node = lay_node_trong_cay(tx, nhan, id_thong_bao)
        da_ghi = 0
        for bat_dau in range(0, len(cac_node), kich_thuoc_batch):
            batch = cac_node[bat_dau : bat_dau + kich_thuoc_batch]
            cac_vector = model.encode(
                [node["text"] for node in batch],
                batch_size=kich_thuoc_batch,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            cac_dong = [
                {"id": node["id"], "embedding": vector.tolist()}
                for node, vector in zip(batch, cac_vector, strict=True)
            ]
            save_embeddings(tx, nhan, cac_dong)
            da_ghi += len(cac_dong)
        ket_qua[nhan] = da_ghi
    return ket_qua


# Nhập cây mới và embedding; lỗi ở bước nào cũng rollback toàn transaction.
def them_thong_bao_kem_embedding(
    tx: Any,
    du_lieu: dict[str, Any],
    id_thong_bao: str,
    model: Any,
    kich_thuoc_batch: int,
) -> dict[str, Any]:
    so_luong_nut = them_thong_bao_moi(tx, du_lieu, id_thong_bao)
    so_luong_embedding = tao_embedding_trong_transaction(
        tx,
        id_thong_bao,
        model,
        kich_thuoc_batch,
    )
    return {
        "so_luong_nut": so_luong_nut,
        "so_luong_embedding": so_luong_embedding,
    }


# Nạp model trước khi mở transaction để lỗi model không tạo dữ liệu dở dang.
def nap_model_embedding(ten_model: str, thiet_bi: str, so_chieu_yeu_cau: int) -> Any:
    from sentence_transformers import SentenceTransformer

    print(f"Đang nạp model {ten_model}...")
    model = SentenceTransformer(ten_model, device=thiet_bi)
    so_chieu = model.get_embedding_dimension()
    if so_chieu != so_chieu_yeu_cau:
        raise ValueError(
            f"Model trả về {so_chieu} chiều, cần {so_chieu_yeu_cau} chiều."
        )
    return model


# Nhập đúng một file mới, tạo embedding và không gọi thao tác xóa nào.
def nhap_file_moi(duong_dan: Path) -> dict[str, Any]:
    du_lieu = doc_file_chunks(duong_dan)
    id_thong_bao = lay_id_thong_bao(du_lieu)
    cau_hinh = load_settings()
    ket_noi = Neo4jConnection(cau_hinh)

    try:
        ket_noi.verify()
        ket_noi.create_constraints()
        with ket_noi.driver.session(database=ket_noi.database) as phien:
            da_ton_tai = phien.run(
                "MATCH (tb:ThongBao {id: $id}) RETURN tb.id AS id LIMIT 1",
                id=id_thong_bao,
            ).single()
            if da_ton_tai is not None:
                raise ValueError(
                    f"ThongBao '{id_thong_bao}' đã tồn tại; "
                    "không có dữ liệu nào được thay đổi."
                )
        model = nap_model_embedding(
            cau_hinh.embedding_model_name,
            cau_hinh.embedding_device,
            cau_hinh.embedding_dimension,
        )
        ket_qua = ket_noi.execute_write(
            lambda tx: them_thong_bao_kem_embedding(
                tx,
                du_lieu,
                id_thong_bao,
                model,
                cau_hinh.embedding_batch_size,
            )
        )
        return {
            "trang_thai": "thanh_cong",
            "id_thong_bao": id_thong_bao,
            "model_embedding": cau_hinh.embedding_model_name,
            "so_chieu_embedding": cau_hinh.embedding_dimension,
            **ket_qua,
        }
    finally:
        ket_noi.close()


# Đọc đường dẫn file chunks từ dòng lệnh.
def doc_tham_so() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Thêm một file chunks mới và embedding vào KG, "
            "không xóa hoặc ghi đè dữ liệu cũ."
        )
    )
    parser.add_argument("file_chunks", type=Path)
    return parser.parse_args()


# Chạy importer và in kết quả dạng JSON.
def main() -> int:
    cau_hinh_console_utf8()
    tham_so = doc_tham_so()
    try:
        ket_qua = nhap_file_moi(tham_so.file_chunks)
        print(json.dumps(ket_qua, ensure_ascii=False, indent=2))
        return 0
    except Exception as loi:
        print(f"[LỖI] {loi}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
