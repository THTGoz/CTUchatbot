from __future__ import annotations

from collections.abc import Iterable


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _join_parts(parts: Iterable[object]) -> str:
    result: list[str] = []
    for value in (_clean(part) for part in parts):
        if not value:
            continue
        if result and result[-1].casefold() == value.casefold():
            continue
        result.append(value)
    return "\n\n".join(result)


def build_muc_text(
    ten_thong_bao: str,
    context_cha: list[str],
    noi_dung: str,
) -> str:
    return _join_parts([ten_thong_bao, *context_cha, noi_dung])


_INDEX_HEADERS = {"tt", "stt"}


def _is_index_column(header: object) -> bool:
    """Cột đánh số thứ tự (TT/STT): ô trống ở đây thường có chủ đích
    (ví dụ dòng "Cộng"/"Tổng cộng"), không phải do gộp ô (rowspan)."""
    return _clean(header).casefold() in _INDEX_HEADERS


def forward_fill_rows(
    cot: list[str],
    rows: list[list[object]],
) -> list[list[str]]:
    """Điền giá trị còn thiếu trong bảng do ô bị gộp theo chiều dọc (rowspan).

    Khi trích xuất bảng từ PDF, một ô rowspan (ví dụ cột "Khóa" áp dụng cho
    nhiều dòng) thường chỉ còn giá trị ở dòng đầu tiên, các dòng sau bị để
    trống. Nếu không xử lý, các dòng sau sẽ mất ngữ cảnh quan trọng khi tạo
    text độc lập cho từng DongBang.

    Với mỗi cột (trừ cột đánh số thứ tự TT/STT), nếu ô hiện tại trống thì
    lấy giá trị không rỗng gần nhất phía trên trong cùng cột. Không áp dụng
    cho cột TT/STT vì ô trống ở đó thường là dòng tổng hợp có chủ đích,
    không phải do gộp ô.
    """
    last_seen: dict[int, str] = {}
    filled_rows: list[list[str]] = []
    for row in rows:
        filled_row: list[str] = []
        for index, header in enumerate(cot):
            value = _clean(row[index]) if index < len(row) else ""
            if not value and not _is_index_column(header):
                value = last_seen.get(index, "")
            if value:
                last_seen[index] = value
            filled_row.append(value)
        filled_rows.append(filled_row)
    return filled_rows


def build_dongbang_noi_dung(
    cot: list[str],
    gia_tri: list[object],
) -> str:
    """Tạo phần nội dung thực của một dòng bảng, không kèm ngữ cảnh cha."""
    lines: list[str] = []
    for index, column in enumerate(cot):
        header = _clean(column)
        value = _clean(gia_tri[index]) if index < len(gia_tri) else ""
        if header and value:
            lines.append(f"{header}: {value}")

    return "\n".join(lines)


def build_dongbang_text(
    ten_thong_bao: str,
    context_cha: list[str],
    tieu_de_bang: str,
    cot: list[str],
    gia_tri: list[object],
) -> str:
    noi_dung_dong = build_dongbang_noi_dung(cot, gia_tri)

    return _join_parts([
        ten_thong_bao,
        *context_cha,
        tieu_de_bang,
        noi_dung_dong,
    ])
