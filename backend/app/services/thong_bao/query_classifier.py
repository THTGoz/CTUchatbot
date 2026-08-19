#Phân loại thông báo
from dataclasses import dataclass

from app.services.thong_bao.utils import bo_dau


# Chỉ dùng các cụm có tính phân biệt cao. Không dùng từ quá rộng như
# "học kỳ", "sinh viên", "ngày", "kế hoạch", "học phần" đứng riêng.
_TYPE_SIGNALS: dict[str, tuple[str, ...]] = {
    "xoa_lop_hoc_phan": (
        "xoa lop hoc phan",
        "lop hoc phan bi xoa",
        "huy lop hoc phan",
        "lop hoc phan bi huy",
        "si so khong du",
        "khong du mo lop",
    ),
    "xet_chuyen_nganh": (
        "chuyen nganh",
        "doi nganh",
        "thay doi nganh hoc",
    ),
    "diem_ren_luyen": (
        "diem ren luyen",
        "danh gia diem ren luyen",
        "drl",
    ),
    "dang_ky_hoc_phan": (
        "dang ky hoc phan",
        "ke hoach dang ky hoc phan",
        "ke hoach giang day",
        "ke hoach hoc tap",
    ),
    "lich_nghi": (
        "lich nghi",
        "nghi le",
        "nghi tet",
        "tet am lich",
        "quoc khanh",
        "gio to hung vuong",
        "quoc te lao dong",
    ),
}


@dataclass(frozen=True)
class NotificationTypeClassification:
    """Kết quả phân loại; notice_type=None nghĩa là không đủ chắc chắn để lọc."""

    notice_type: str | None
    matched_signals: tuple[str, ...] = ()
    ambiguous_types: tuple[str, ...] = ()

    @property
    def confident(self) -> bool:
        return self.notice_type is not None


def classify_notification_type(query: str) -> NotificationTypeClassification:
    """Phân loại bằng cụm từ đặc trưng; mơ hồ thì không ép một loại thông báo."""
    normalized = " ".join(bo_dau(query).split())
    if not normalized:
        return NotificationTypeClassification(notice_type=None)

    matches: dict[str, list[str]] = {}
    for notice_type, signals in _TYPE_SIGNALS.items():
        matched = [signal for signal in signals if signal in normalized]
        if matched:
            matches[notice_type] = matched

    if not matches:
        return NotificationTypeClassification(notice_type=None)

    if len(matches) > 1:
        return NotificationTypeClassification(
            notice_type=None,
            matched_signals=tuple(
                signal
                for notice_type in matches
                for signal in matches[notice_type]
            ),
            ambiguous_types=tuple(matches),
        )

    notice_type, matched = next(iter(matches.items()))
    return NotificationTypeClassification(
        notice_type=notice_type,
        matched_signals=tuple(matched),
    )
