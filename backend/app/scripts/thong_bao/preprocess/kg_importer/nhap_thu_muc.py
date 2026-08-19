r"""Nhập riêng một thư mục ``*_chunks.json`` vào KG Thông báo.

Khác với ``main.py``, tệp này không xóa toàn bộ nhánh Thông báo. Mỗi tài liệu
được thay thế độc lập trong một transaction: nếu nhập lỗi, dữ liệu cũ của đúng
tài liệu đó vẫn được giữ nguyên nhờ Neo4j rollback.

Ví dụ:
    python nhap_thu_muc.py D:\du_lieu\06_chunks
    python nhap_thu_muc.py D:\du_lieu\mot_file_chunks.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


from .config import Settings, load_settings
from .importer.thongbao_importer import import_thongbao
from .neo4j_connection import Neo4jConnection
from .utils.id_utils import thongbao_id_from_filename


CAC_NHAN_THONG_BAO = ("ThongBao", "TaiLieu", "Muc", "Bang", "DongBang")


# Trả thời điểm hiện tại theo định dạng dùng trong báo cáo JSON.
def thoi_diem_hien_tai() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# Lấy các tệp chunks từ một tệp đơn hoặc một thư mục riêng.
def tim_tep_chunks(duong_dan: Path, de_quy: bool = False) -> list[Path]:
    duong_dan = duong_dan.expanduser().resolve()
    if duong_dan.is_file():
        if not duong_dan.name.casefold().endswith("_chunks.json"):
            raise ValueError("Tệp đầu vào phải có hậu tố _chunks.json.")
        return [duong_dan]
    if not duong_dan.is_dir():
        raise FileNotFoundError(f"Không tìm thấy tệp hoặc thư mục: {duong_dan}")

    mau = "**/*_chunks.json" if de_quy else "*_chunks.json"
    cac_tep = sorted(tep for tep in duong_dan.glob(mau) if tep.is_file())
    if not cac_tep:
        raise FileNotFoundError(f"Không có tệp *_chunks.json trong {duong_dan}")
    return cac_tep


# Đọc và kiểm tra cấu trúc JSON cấp gốc trước khi mở transaction ghi.
def doc_chunks(duong_dan: Path) -> dict[str, Any]:
    with duong_dan.open("r", encoding="utf-8") as tep:
        du_lieu = json.load(tep)
    if not isinstance(du_lieu, dict):
        raise TypeError(f"JSON gốc của {duong_dan.name} phải là object.")
    metadata = du_lieu.get("metadata")
    tai_lieu = du_lieu.get("tai_lieu")
    if not isinstance(metadata, dict) or not isinstance(tai_lieu, list):
        raise TypeError(
            f"{duong_dan.name} phải có metadata object và tai_lieu list."
        )
    return du_lieu


# Lấy ID thông báo từ metadata bằng đúng quy tắc của importer hiện tại.
def lay_id_thong_bao(du_lieu: dict[str, Any]) -> str:
    metadata = du_lieu.get("metadata") or {}
    return thongbao_id_from_filename(str(metadata.get("ten_file") or ""))


# Xóa và nhập lại đúng một cây Thông báo trong cùng transaction.
def thay_the_mot_thong_bao(
    tx: Any,
    du_lieu: dict[str, Any],
    id_thong_bao: str,
) -> dict[str, Any]:
    ban_ghi = tx.run(
        """
        MATCH (tb:ThongBao {id: $id_thong_bao})
        OPTIONAL MATCH (tb)-[
            :CO_TAI_LIEU|CO_MUC|CO_BANG|CO_DONG*0..
        ]->(nut_con)
        WITH collect(DISTINCT tb) + collect(DISTINCT nut_con) AS cac_nut
        UNWIND cac_nut AS nut
        WITH DISTINCT nut
        DETACH DELETE nut
        RETURN count(nut) AS so_nut_da_xoa
        """,
        id_thong_bao=id_thong_bao,
    ).single()
    so_nut_da_xoa = int(ban_ghi["so_nut_da_xoa"]) if ban_ghi else 0
    so_luong_nut = import_thongbao(tx, du_lieu)
    return {
        "id_thong_bao": id_thong_bao,
        "so_nut_da_xoa": so_nut_da_xoa,
        "so_luong_nut": so_luong_nut,
    }


# Ghi báo cáo nhập thư mục ra JSON khi người gọi cung cấp đường dẫn.
def ghi_bao_cao(bao_cao: dict[str, Any], duong_dan: Path | None) -> None:
    if duong_dan is None:
        return
    duong_dan = duong_dan.expanduser().resolve()
    duong_dan.parent.mkdir(parents=True, exist_ok=True)
    duong_dan.write_text(
        json.dumps(bao_cao, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# Nhập độc lập các chunks trong thư mục mà không đụng tới thông báo ngoài phạm vi.
def nhap_thu_muc(
    duong_dan: Path,
    *,
    de_quy: bool = False,
    duong_dan_bao_cao: Path | None = None,
    cau_hinh: Settings | None = None,
) -> dict[str, Any]:
    cau_hinh = cau_hinh or load_settings()
    cac_tep = tim_tep_chunks(duong_dan, de_quy=de_quy)
    cac_goi_du_lieu = [(tep, doc_chunks(tep)) for tep in cac_tep]

    cac_id = [lay_id_thong_bao(du_lieu) for _, du_lieu in cac_goi_du_lieu]
    id_trung = sorted(id_ for id_, so_lan in Counter(cac_id).items() if so_lan > 1)
    if id_trung:
        raise ValueError(f"Nhiều tệp tạo cùng ID ThongBao: {', '.join(id_trung)}")

    bao_cao: dict[str, Any] = {
        "bat_dau_luc": thoi_diem_hien_tai(),
        "ket_thuc_luc": None,
        "database": cau_hinh.neo4j_database,
        "duong_dan_dau_vao": str(Path(duong_dan).expanduser().resolve()),
        "tong_so_tep": len(cac_tep),
        "so_tep_thanh_cong": 0,
        "so_tep_that_bai": 0,
        "so_nut_da_xoa": 0,
        "so_luong_nut": {nhan: 0 for nhan in CAC_NHAN_THONG_BAO},
        "cac_tep": [],
    }

    ket_noi = Neo4jConnection(cau_hinh)
    try:
        ket_noi.verify()
        ket_noi.create_constraints()
        tong_so_luong: Counter[str] = Counter()
        for tep, du_lieu in cac_goi_du_lieu:
            ket_qua_tep: dict[str, Any] = {"tep": tep.name, "trang_thai": "that_bai"}
            try:
                id_thong_bao = lay_id_thong_bao(du_lieu)
                ket_qua = ket_noi.execute_write(
                    lambda tx, goi=du_lieu, ma=id_thong_bao: thay_the_mot_thong_bao(
                        tx, goi, ma
                    )
                )
                so_luong = dict(ket_qua["so_luong_nut"])
                tong_so_luong.update(so_luong)
                bao_cao["so_nut_da_xoa"] += int(ket_qua["so_nut_da_xoa"])
                bao_cao["so_tep_thanh_cong"] += 1
                ket_qua_tep.update({
                    "trang_thai": "thanh_cong",
                    "id_thong_bao": id_thong_bao,
                    "so_nut_da_xoa": ket_qua["so_nut_da_xoa"],
                    "so_luong_nut": so_luong,
                })
            except Exception as loi:
                bao_cao["so_tep_that_bai"] += 1
                ket_qua_tep["loi"] = str(loi)
            bao_cao["cac_tep"].append(ket_qua_tep)

        bao_cao["so_luong_nut"] = {
            nhan: tong_so_luong[nhan] for nhan in CAC_NHAN_THONG_BAO
        }
        bao_cao["ket_thuc_luc"] = thoi_diem_hien_tai()
        ghi_bao_cao(bao_cao, duong_dan_bao_cao)
        return bao_cao
    finally:
        ket_noi.close()


# Đọc tham số dòng lệnh của chế độ nhập thư mục riêng.
def doc_tham_so() -> argparse.Namespace:
    bo_doc = argparse.ArgumentParser(
        description=(
            "Nhập riêng một tệp hoặc thư mục *_chunks.json; "
            "không xóa toàn bộ KG Thông báo."
        )
    )
    bo_doc.add_argument("duong_dan", type=Path)
    bo_doc.add_argument("--de-quy", action="store_true")
    bo_doc.add_argument("--bao-cao", type=Path)
    return bo_doc.parse_args()


# Chạy importer thư mục và trả mã thoát theo số tệp thất bại.
def chay_chinh() -> int:
    tham_so = doc_tham_so()
    try:
        bao_cao = nhap_thu_muc(
            tham_so.duong_dan,
            de_quy=tham_so.de_quy,
            duong_dan_bao_cao=tham_so.bao_cao,
        )
        print(json.dumps(bao_cao, ensure_ascii=False, indent=2))
        return 0 if bao_cao["so_tep_that_bai"] == 0 else 1
    except Exception as loi:
        print(f"[LỖI] {loi}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(chay_chinh())
