"""Deterministic academic-year/semester constraints for notifications."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.thong_bao.utils import bo_dau


@dataclass(frozen=True)
class MocThoiGian:
    """Các ràng buộc thời gian được đọc trực tiếp từ câu hỏi Thông báo."""

    nam_hoc_bat_dau: int | None = None
    nam_hoc_ket_thuc: int | None = None
    nam: int | None = None
    hoc_ky: int | None = None

    @property
    def co_thoi_gian(self) -> bool:
        """Cho biết câu hỏi có chứa ít nhất một mốc năm hoặc học kỳ."""
        return any((self.nam_hoc_bat_dau, self.nam_hoc_ket_thuc, self.nam, self.hoc_ky))


def doc_moc_thoi_gian(cau_hoi: str) -> MocThoiGian:
    khong_dau = bo_dau(cau_hoi)

    # Ưu tiên cặp năm học đầy đủ, ví dụ 2026-2027, trước khi đọc một năm đơn.
    nam_hoc = re.search(r"(?<!\d)(20\d{2})\D+(20\d{2})(?!\d)", khong_dau)
    hoc_ky = re.search(r"\b(?:hoc\s*ky|hk)\s*([123])\b", khong_dau)
    if nam_hoc:
        return MocThoiGian(
            nam_hoc_bat_dau=int(nam_hoc.group(1)),
            nam_hoc_ket_thuc=int(nam_hoc.group(2)),
            hoc_ky=int(hoc_ky.group(1)) if hoc_ky else None,
        )
    # Nếu không có cặp năm học thì giữ năm đơn để lọc theo năm ban hành.
    nam = re.search(r"(?<!\d)(20\d{2})(?!\d)", khong_dau)
    return MocThoiGian(
        nam=int(nam.group(1)) if nam else None,
        hoc_ky=int(hoc_ky.group(1)) if hoc_ky else None,
    )
