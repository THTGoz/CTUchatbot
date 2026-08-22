"""Truy xuất thông báo'"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from app.services.common.candidate import (
    DOMAIN_THONG_BAO,
    Candidate,
    make_candidate,
    merge_candidates,
)
from app.services.thong_bao.query_classifier import (
    NotificationTypeClassification,
    classify_notification_type,
)
from app.services.thong_bao.temporal import MocThoiGian, doc_moc_thoi_gian
from app.services.thong_bao.utils import bo_dau


CAC_LABEL_THONG_BAO = ("Muc", "DongBang")
ReadQuery = Callable[[str, dict[str, Any]], list[dict[str, Any]]]


@dataclass(frozen=True)
class ThongBaoRetrievalResult:
    """Kết quả quan sát được của từng tầng retrieval Thông báo."""

    temporal_scope: MocThoiGian
    type_classification: NotificationTypeClassification
    notification_ids: list[str]
    exact_values: dict[str, list[str]]
    exact_candidates: list[Candidate]
    grouped_exact_candidates: list[Candidate]
    vector_candidates: list[Candidate]
    candidates: list[Candidate]


def _shared_reader(cypher: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
    """Chạy Cypher bằng Neo4j driver dùng chung của backend."""
    from app.db.neo4j import read_query

    return read_query(cypher, parameters)


def _positive_int_env(name: str, default: int) -> int:
    """Đọc một cấu hình số nguyên dương và dùng default nếu cấu hình sai."""
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _chuan_hoa_gia_tri(value: object) -> str:
    """Chuẩn hóa khoảng trắng và dấu tiếng Việt trước khi exact-match."""
    return re.sub(r"\s+", " ", bo_dau(value)).strip()


def _loai_exact_cua_header(header: str) -> str | None:
    """Ánh xạ tiêu đề cột bảng về loại thực thể có thể exact-match."""
    khong_dau = _chuan_hoa_gia_tri(header)
    if "ma hp" in khong_dau or "ma hoc phan" in khong_dau:
        return "ma_hoc_phan"
    if "ma sv" in khong_dau or "ma sinh vien" in khong_dau:
        return "ma_sinh_vien"
    if khong_dau in {"khoa", "khoa hoc"}:
        return "khoa"
    if "nganh" in khong_dau:
        return "nganh"
    return None


def _gia_tri_khop(loai: str, gia_tri_o: object, gia_tri_exact: str) -> bool:
    """Kiểm tra giá trị một ô bảng có thỏa một giá trị exact hay không."""
    cell = _chuan_hoa_gia_tri(gia_tri_o)
    exact = _chuan_hoa_gia_tri(gia_tri_exact)
    if loai == "khoa":
        cell_number = re.search(r"(?<!\d)(\d{2})(?!\d)", cell)
        exact_number = re.search(r"(?<!\d)(\d{2})(?!\d)", exact)
        return bool(cell_number and exact_number and cell_number.group(1) == exact_number.group(1))
    if loai in {"ma_hoc_phan", "ma_sinh_vien"}:
        return cell.upper() == exact.upper()
    return exact == cell or exact in cell


def _danh_sach_exact(value: object) -> list[str]:
    """Chuẩn hóa exact metadata cũ/mới về list[str] và loại trùng theo thứ tự."""
    if value is None:
        return []
    raw_values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        text = str(item or "").strip()
        if not text:
            continue
        key = _chuan_hoa_gia_tri(text)
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _gia_tri_khop_bat_ky(
    loai: str,
    gia_tri_o: object,
    gia_tri_exact: object,
) -> bool:
    """OR giữa các exact value cùng loại; dùng cho K48/K50, CT219/CT177, ..."""
    return any(
        _gia_tri_khop(loai, gia_tri_o, value)
        for value in _danh_sach_exact(gia_tri_exact)
    )


def doc_gia_tri_exact_co_ban(cau_hoi: str) -> dict[str, list[str]]:
    exact: dict[str, list[str]] = {}
    courses = re.findall(
        r"(?<![A-Z0-9])([A-Z]{2,4}\d{3}[A-Z]?)(?![A-Z0-9])",
        cau_hoi.upper(),
    )
    students = re.findall(
        r"(?<![A-Z0-9])([A-Z]\d{7})(?![A-Z0-9])",
        cau_hoi.upper(),
    )
    cohorts = re.findall(r"\b(?:khoa|k)\s*(\d{2})\b", bo_dau(cau_hoi))

    if values := _danh_sach_exact(courses):
        exact["ma_hoc_phan"] = values
    if values := _danh_sach_exact(students):
        exact["ma_sinh_vien"] = values
    if values := _danh_sach_exact([f"K{cohort}" for cohort in cohorts]):
        exact["khoa"] = values
    return exact


def _group_exact_rows_by_table(candidates: list[Candidate]) -> list[Candidate]:
    """
    Giữ một dòng cosine cao nhất cho mỗi (thông báo, bảng, exact value).

    Nếu câu hỏi chứa nhiều giá trị exact cùng loại, ví dụ K48 và K50,
    mỗi giá trị được giữ một representative riêng dù cùng nằm trong một bảng.
    """
    rows_without_table: list[Candidate] = []
    by_table_and_exact: dict[tuple[Any, ...], Candidate] = {}

    for candidate in candidates:
        metadata = candidate["metadata"]
        notification_id = str(metadata.get("notification_id") or "")
        table_id = str(metadata.get("parent_table_id") or "")

        if not table_id:
            rows_without_table.append(candidate)
            continue

        exact_columns = metadata.get("exact_columns") or {}
        exact_signature = tuple(
            (
                exact_type,
                tuple(
                    _chuan_hoa_gia_tri(value)
                    for value in _danh_sach_exact(values)
                ),
            )
            for exact_type, values in sorted(exact_columns.items())
        )

        key = (notification_id, table_id, exact_signature)
        current = by_table_and_exact.get(key)
        if current is None or candidate["cosine_score"] > current["cosine_score"]:
            by_table_and_exact[key] = candidate

    return sorted(
        [*rows_without_table, *by_table_and_exact.values()],
        key=lambda item: (-item["cosine_score"], item["node_id"]),
    )


def _so_nguyen(value: object) -> int:
    """Đổi metadata thời gian về số nguyên an toàn cho ranking."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _ngay_ban_hanh_key(value: object) -> tuple[int, int, int]:
    """Chuẩn hóa YYYY, YYYY-MM hoặc YYYY-MM-DD thành khóa thời gian."""
    parts = [int(item) for item in re.findall(r"\d+", str(value or ""))]
    if not parts:
        return (0, 0, 0)
    year = parts[0] if 1000 <= parts[0] <= 9999 else 0
    month = parts[1] if len(parts) >= 2 and 1 <= parts[1] <= 12 else 0
    day = parts[2] if len(parts) >= 3 and 1 <= parts[2] <= 31 else 0
    return (year, month, day)


def _notification_time_key(candidate: Candidate) -> tuple[int, int, int, int, int, int]:
    """Khóa mới→cũ: năm học, học kỳ, rồi ngày ban hành."""
    metadata = candidate["metadata"]
    issue_year, issue_month, issue_day = _ngay_ban_hanh_key(
        metadata.get("ngay_ban_hanh")
    )
    if not issue_year:
        issue_year = _so_nguyen(metadata.get("nam_ban_hanh"))

    school_end = _so_nguyen(metadata.get("nam_hoc_ket_thuc"))
    school_start = _so_nguyen(metadata.get("nam_hoc_bat_dau"))
    semester = _so_nguyen(metadata.get("hoc_ky"))

    # Với văn bản có năm học, năm kết thúc là mốc chính. Với văn bản chỉ có
    # năm/ngày ban hành (ví dụ lịch nghỉ), dùng năm ban hành làm mốc tương ứng.
    period_year = school_end or school_start or issue_year
    return (
        period_year,
        school_start,
        semester,
        issue_year,
        issue_month,
        issue_day,
    )


def select_notification_top_k(
    candidates: Iterable[Candidate],
    top_k: int,
) -> list[Candidate]:
    """Chọn top-k: cosine giữa các loại, thời gian mới trước trong cùng loại."""
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero")

    # merge_candidates vừa deduplicate vừa tạo thứ tự cosine toàn cục ban đầu.
    ranked = merge_candidates([candidates])
    positions_by_type: dict[str, list[int]] = defaultdict(list)
    candidates_by_type: dict[str, list[Candidate]] = defaultdict(list)

    for index, candidate in enumerate(ranked):
        notice_type = str(candidate["metadata"].get("loai_thong_bao") or "").strip()
        if not notice_type:
            continue
        positions_by_type[notice_type].append(index)
        candidates_by_type[notice_type].append(candidate)

    # Chỉ hoán đổi candidate bên trong các vị trí vốn thuộc cùng một loại thông
    # báo. Vì vậy giữa các loại khác nhau vẫn giữ cạnh tranh cosine ban đầu, còn
    # trong cùng loại thì bản mới hơn được đẩy lên trước trước khi cắt top_k.
    for notice_type, group in candidates_by_type.items():
        group.sort(key=lambda item: item["node_id"])
        group.sort(
            key=lambda item: (_notification_time_key(item), item["cosine_score"]),
            reverse=True,
        )
        for index, candidate in zip(positions_by_type[notice_type], group):
            ranked[index] = candidate

    return ranked[:top_k]


def _tu_ban_ghi(
    item: dict[str, Any],
    *,
    source: str,
    exact_columns: dict[str, list[str]] | None = None,
) -> Candidate:
    """Chuyển một record Neo4j thành candidate chung của chatbot."""
    metadata: dict[str, Any] = {
        "notification_id": item.get("notification_id"),
        "loai_thong_bao": item.get("loai_thong_bao"),
        "nam_hoc": item.get("nam_hoc"),
        "nam_hoc_bat_dau": item.get("nam_hoc_bat_dau"),
        "nam_hoc_ket_thuc": item.get("nam_hoc_ket_thuc"),
        "hoc_ky": item.get("hoc_ky"),
        "ngay_ban_hanh": item.get("ngay_ban_hanh"),
        "nam_ban_hanh": item.get("nam_ban_hanh"),
        "ten_thong_bao": item.get("ten_thong_bao"),
        "parent_table_id": item.get("parent_table_id"),
        "table_headers": item.get("table_headers") or [],
    }
    if exact_columns:
        metadata["exact_columns"] = exact_columns
    return make_candidate(
        node_id=item.get("node_id"),
        label=item.get("label"),
        cosine_score=item.get("score"),
        properties=item.get("properties"),
        source=source,
        domain=DOMAIN_THONG_BAO,
        metadata=metadata,
    )


class ThongBaoRetriever:
    """Thực hiện temporal filter, exact retrieval và vector retrieval cho Thông báo."""

    def __init__(
        self,
        *,
        top_k_per_label: int | None = None,
        reader: ReadQuery | None = None,
    ) -> None:
        """Khởi tạo retriever với giới hạn từng label và reader có thể thay thế khi test."""
        self._top_k_per_label = top_k_per_label or _positive_int_env("THONG_BAO_TOP_K_PER_LABEL", 3)
        self._read = reader or _shared_reader

    def _tai_lieu_duoc_phep(
        self,
        moc: MocThoiGian,
        notice_type: str | None = None,
    ) -> list[str]:
        """Chọn tập thông báo theo thời gian và loại chắc chắn nếu có."""
        if moc.co_thoi_gian:
            cypher = """
            MATCH (tb:ThongBao)
            WHERE tb.loai_thong_bao <> 'thong_bao_khac'
              AND ($loai IS NULL OR tb.loai_thong_bao = $loai)
              AND ($bat_dau IS NULL OR tb.nam_hoc_bat_dau = $bat_dau)
              AND ($ket_thuc IS NULL OR tb.nam_hoc_ket_thuc = $ket_thuc)
              AND ($hoc_ky IS NULL OR tb.hoc_ky = $hoc_ky)
              AND (
                  $nam IS NULL
                  OR tb.nam_ban_hanh = $nam
                  OR tb.nam_hoc_bat_dau = $nam
                  OR tb.nam_hoc_ket_thuc = $nam
              )
            RETURN tb.id AS id
            ORDER BY tb.id
            """
            parameters = {
                "bat_dau": moc.nam_hoc_bat_dau,
                "ket_thuc": moc.nam_hoc_ket_thuc,
                "nam": moc.nam,
                "hoc_ky": moc.hoc_ky,
                "loai": notice_type,
            }
        else:
            cypher = """
            MATCH (tb:ThongBao)
            WHERE tb.loai_thong_bao <> 'thong_bao_khac'
              AND ($loai IS NULL OR tb.loai_thong_bao = $loai)
            WITH tb.loai_thong_bao AS loai,
                 max(tb.nam_hoc_ket_thuc) AS nam_hoc_ket_thuc_moi_nhat,
                 max(tb.nam_ban_hanh) AS nam_ban_hanh_moi_nhat
            MATCH (tb:ThongBao {loai_thong_bao: loai})
            WHERE tb.loai_thong_bao <> 'thong_bao_khac'
              AND (
                  tb.nam_hoc_ket_thuc = nam_hoc_ket_thuc_moi_nhat
                  OR (
                      nam_hoc_ket_thuc_moi_nhat IS NULL
                      AND tb.nam_hoc_ket_thuc IS NULL
                      AND tb.nam_ban_hanh = nam_ban_hanh_moi_nhat
                  )
              )
            RETURN tb.id AS id
            ORDER BY loai, tb.id
            """
            parameters = {"loai": notice_type}
        return [str(item["id"]) for item in self._read(cypher, parameters)]

    def _exact_columns(self, cau_hoi: str, thong_bao_ids: list[str]) -> dict[str, list[str]]:
        """Rút các mã học phần, mã sinh viên, khóa và ngành để exact-match bảng."""
        exact = doc_gia_tri_exact_co_ban(cau_hoi)

        # Tên ngành được lấy từ chính các bảng đang được phép tra cứu để tránh danh mục cứng.
        major_rows = self._read(
            """
            MATCH (tb:ThongBao)-[:CO_TAI_LIEU]->(:TaiLieu)-[:CO_MUC*1..]->(:Muc)-[:CO_BANG]->(b:Bang)-[:CO_DONG]->(d:DongBang)
            WHERE tb.id IN $ids
            UNWIND range(0, size(b.cot) - 1) AS vi_tri
            WITH b, d, vi_tri
            WHERE vi_tri < size(d.gia_tri)
              AND (toLower(b.cot[vi_tri]) CONTAINS 'ngành' OR toLower(b.cot[vi_tri]) CONTAINS 'nganh')
            RETURN DISTINCT d.gia_tri[vi_tri] AS gia_tri
            """,
            {"ids": thong_bao_ids},
        )
        query_without_accents = bo_dau(cau_hoi)
        values = sorted(
            (str(item.get("gia_tri") or "").strip() for item in major_rows),
            key=len,
            reverse=True,
        )
        matched_majors = [
            value
            for value in values
            if value and bo_dau(value) in query_without_accents
        ]
        if matched_majors:
            exact["nganh"] = _danh_sach_exact(matched_majors)
        return exact

    def _exact(
        self,
        vector: list[float],
        thong_bao_ids: list[str],
        exact_columns: dict[str, list[str]],
    ) -> list[Candidate]:
        """Exact ngay trong Cypher, sau đó giữ lớp kiểm tra Python để bảo toàn kết quả."""
        if not exact_columns:
            return []

        # Header của Bang là dữ liệu động, nên mỗi loại exact được ánh xạ thành
        # một điều kiện Cypher trên đúng vị trí cột. Neo4j nhờ đó chỉ trả về
        # các DongBang có khả năng thỏa exact thay vì trả toàn bộ dòng của cây.
        header_expr = (
            "toLower(trim(replace(replace(toString(b.cot[i]), '  ', ' '), '  ', ' ')))"
        )
        header_conditions = {
            "ma_hoc_phan": (
                f"({header_expr} CONTAINS 'mã hp' OR {header_expr} CONTAINS 'ma hp' "
                f"OR {header_expr} CONTAINS 'mã học phần' OR {header_expr} CONTAINS 'ma hoc phan')"
            ),
            "ma_sinh_vien": (
                f"({header_expr} CONTAINS 'mã sv' OR {header_expr} CONTAINS 'ma sv' "
                f"OR {header_expr} CONTAINS 'mã sinh viên' OR {header_expr} CONTAINS 'ma sinh vien')"
            ),
            "khoa": (
                f"({header_expr} IN ['khóa', 'khoa', 'khóa học', 'khoa hoc'])"
            ),
            "nganh": (
                f"({header_expr} CONTAINS 'ngành' OR {header_expr} CONTAINS 'nganh')"
            ),
        }

        parameters: dict[str, Any] = {
            "ids": thong_bao_ids,
            "vector": vector,
        }
        relevant_header_clauses: list[str] = []
        match_clauses: list[str] = []

        for exact_type, raw_exact_values in exact_columns.items():
            header_condition = header_conditions.get(exact_type)
            exact_values = _danh_sach_exact(raw_exact_values)
            if header_condition is None or not exact_values:
                continue

            header_exists = (
                "any(i IN range(0, size(b.cot) - 1) "
                f"WHERE {header_condition})"
            )

            parameter_name = f"exact_{exact_type}"
            parameters[parameter_name] = exact_values

            if exact_type in {"ma_hoc_phan", "ma_sinh_vien"}:
                value_condition = (
                    f"any(expected IN ${parameter_name} WHERE "
                    "toUpper(trim(toString(d.gia_tri[i]))) = "
                    "toUpper(trim(toString(expected))))"
                )
            elif exact_type == "khoa":
                # OR giữa các khóa cùng loại (K48 hoặc K50); Python vẫn kiểm
                # tra lại bằng cùng semantics exact để tránh regex pre-filter sai.
                patterns: list[str] = []
                for exact_value in exact_values:
                    match = re.search(r"(?<!\d)(\d{2})(?!\d)", exact_value)
                    if match:
                        patterns.append(
                            rf".*(^|\D){re.escape(match.group(1))}(\D|$).*"
                        )
                if not patterns:
                    continue
                pattern_name = "exact_khoa_patterns"
                parameters[pattern_name] = patterns
                value_condition = (
                    f"any(pattern IN ${pattern_name} WHERE "
                    "toString(d.gia_tri[i]) =~ pattern)"
                )
            else:  # nganh
                value_condition = (
                    f"any(expected IN ${parameter_name} WHERE "
                    "toLower(trim(toString(d.gia_tri[i]))) CONTAINS "
                    "toLower(trim(toString(expected))))"
                )

            relevant_header_clauses.append(header_exists)
            matching_value = (
                "any(i IN range(0, size(b.cot) - 1) WHERE "
                f"{header_condition} AND i < size(d.gia_tri) AND {value_condition})"
            )
            # AND giữa các loại exact khác nhau; OR giữa nhiều giá trị cùng loại.
            # Ví dụ: (K48 OR K50) AND (CT219 OR CT177).
            match_clauses.append(f"(NOT {header_exists} OR {matching_value})")

        if not relevant_header_clauses:
            return []

        exact_where = "\n              AND ".join(match_clauses)
        relevant_where = " OR ".join(relevant_header_clauses)
        cypher = f"""
        MATCH (tb:ThongBao)-[:CO_TAI_LIEU]->(:TaiLieu)-[:CO_MUC*1..]->(:Muc)
              -[:CO_BANG]->(b:Bang)-[:CO_DONG]->(d:DongBang)
        WHERE tb.id IN $ids
          AND ({relevant_where})
          AND {exact_where}
        RETURN d.id AS node_id, 'DongBang' AS label,
               vector.similarity.cosine(d.embedding, $vector) AS score,
               d{{.*, embedding: null}} AS properties,
               tb.id AS notification_id, tb.loai_thong_bao AS loai_thong_bao,
               tb.nam_hoc AS nam_hoc, tb.nam_hoc_bat_dau AS nam_hoc_bat_dau,
               tb.nam_hoc_ket_thuc AS nam_hoc_ket_thuc, tb.hoc_ky AS hoc_ky,
               tb.ngay_ban_hanh AS ngay_ban_hanh, tb.nam_ban_hanh AS nam_ban_hanh,
               tb.tieu_de AS ten_thong_bao,
               b.id AS parent_table_id, b.cot AS table_headers
        ORDER BY score DESC, node_id
        """
        rows = self._read(cypher, parameters)

        # Vẫn kiểm tra lại bằng đúng hàm cũ để đầu ra và semantics exact không đổi.
        # Khác biệt là số dòng phải đưa từ Neo4j về Python đã được thu hẹp trước.
        result: list[Candidate] = []
        for item in rows:
            headers = item.get("table_headers") or []
            values = (item.get("properties") or {}).get("gia_tri") or []
            constraints = {
                exact_type: exact_values
                for header in headers
                for exact_type in [_loai_exact_cua_header(str(header))]
                if exact_type is not None
                and (exact_values := _danh_sach_exact(exact_columns.get(exact_type)))
            }
            if not constraints:
                continue
            matched_exact_columns: dict[str, list[str]] = {}

            for exact_type, exact_values in constraints.items():
                matched_values: list[str] = []

                for exact_value in exact_values:
                    matched = any(
                        _loai_exact_cua_header(str(header)) == exact_type
                        and index < len(values)
                        and _gia_tri_khop(exact_type, values[index], exact_value)
                        for index, header in enumerate(headers)
                    )
                    if matched:
                        matched_values.append(exact_value)

                if matched_values:
                    matched_exact_columns[exact_type] = matched_values

            # Mỗi loại exact có mặt trong bảng phải khớp ít nhất một giá trị.
            # Candidate chỉ mang những exact value thực sự khớp với dòng này.
            if len(matched_exact_columns) == len(constraints):
                result.append(
                    _tu_ban_ghi(
                        item,
                        source="exact",
                        exact_columns=matched_exact_columns,
                    )
                )
        return result

    def _vector_mot_label(
        self,
        label: str,
        vector: list[float],
        thong_bao_ids: list[str],
    ) -> list[Candidate]:
        """Vector retrieval theo label; DongBang được gom theo bảng trước LIMIT.
        """
        if label == "Muc":
            cypher = """
            MATCH (tb:ThongBao)-[:CO_TAI_LIEU]->(:TaiLieu)-[:CO_MUC*1..]->(node:Muc)
            WHERE tb.id IN $ids AND node.embedding IS NOT NULL
            WITH tb, node,
                 vector.similarity.cosine(node.embedding, $vector) AS score
            ORDER BY score DESC, node.id
            LIMIT $top_k
            RETURN node.id AS node_id, 'Muc' AS label, score,
                   node{.*, embedding: null} AS properties,
                   tb.id AS notification_id, tb.loai_thong_bao AS loai_thong_bao,
                   tb.nam_hoc AS nam_hoc, tb.nam_hoc_bat_dau AS nam_hoc_bat_dau,
                   tb.nam_hoc_ket_thuc AS nam_hoc_ket_thuc, tb.hoc_ky AS hoc_ky,
                   tb.ngay_ban_hanh AS ngay_ban_hanh, tb.nam_ban_hanh AS nam_ban_hanh,
                   tb.tieu_de AS ten_thong_bao,
                   null AS parent_table_id, [] AS table_headers
            """
        elif label == "DongBang":
            cypher = """
            MATCH (tb:ThongBao)-[:CO_TAI_LIEU]->(:TaiLieu)-[:CO_MUC*1..]->(:Muc)
                  -[:CO_BANG]->(b:Bang)-[:CO_DONG]->(node:DongBang)
            WHERE tb.id IN $ids AND node.embedding IS NOT NULL
            WITH tb, b, node,
                 vector.similarity.cosine(node.embedding, $vector) AS score
 
            // Sắp xếp trước khi collect để phần tử đầu tiên của mỗi bảng là
            // DongBang có cosine cao nhất trong chính bảng đó.
            ORDER BY tb.id, b.id, score DESC, node.id
            WITH tb, b, collect({node: node, score: score})[0] AS representative
            WITH tb, b,
                 representative.node AS node,
                 representative.score AS score
 
            // Từ đây mỗi bảng chỉ còn đúng một representative; các bảng mới
            // cạnh tranh trực tiếp bằng cosine trước khi cắt top-k theo label.
            ORDER BY score DESC, node.id
            LIMIT $top_k
            RETURN node.id AS node_id, 'DongBang' AS label, score,
                   node{.*, embedding: null} AS properties,
                   tb.id AS notification_id, tb.loai_thong_bao AS loai_thong_bao,
                   tb.nam_hoc AS nam_hoc, tb.nam_hoc_bat_dau AS nam_hoc_bat_dau,
                   tb.nam_hoc_ket_thuc AS nam_hoc_ket_thuc, tb.hoc_ky AS hoc_ky,
                   tb.ngay_ban_hanh AS ngay_ban_hanh, tb.nam_ban_hanh AS nam_ban_hanh,
                   tb.tieu_de AS ten_thong_bao,
                   b.id AS parent_table_id, b.cot AS table_headers
            """
        else:
            raise ValueError(f"Label ThongBao không hỗ trợ vector retrieval: {label}")

        rows = self._read(
            cypher,
            {
                "ids": thong_bao_ids,
                "vector": vector,
                "top_k": self._top_k_per_label,
            },
        )
        return [_tu_ban_ghi(item, source="vector") for item in rows]

    def retrieve_with_trace(
        self,
        cau_hoi: str,
        vector: list[float] | None = None,
    ) -> ThongBaoRetrievalResult:
        temporal_scope = doc_moc_thoi_gian(cau_hoi)
        type_classification = classify_notification_type(cau_hoi)
        if vector is None:
            from app.services.common.embedding import get_embedding_model

            embeddings = get_embedding_model().get_embedding_batch([cau_hoi])
            vector = embeddings[0] if embeddings else []
        if not vector:
            return ThongBaoRetrievalResult(
                temporal_scope=temporal_scope,
                type_classification=type_classification,
                notification_ids=[],
                exact_values={},
                exact_candidates=[],
                grouped_exact_candidates=[],
                vector_candidates=[],
                candidates=[],
            )

        # Temporal filter luôn chạy trước exact/vector retrieval để giới hạn đúng cây thông báo.
        notification_ids = self._tai_lieu_duoc_phep(
            temporal_scope,
            type_classification.notice_type,
        )
        if not notification_ids:
            return ThongBaoRetrievalResult(
                temporal_scope=temporal_scope,
                type_classification=type_classification,
                notification_ids=[],
                exact_values={},
                exact_candidates=[],
                grouped_exact_candidates=[],
                vector_candidates=[],
                candidates=[],
            )
        exact_columns = self._exact_columns(cau_hoi, notification_ids)
        # Có exact
        if exact_columns:
            exact_candidates = self._exact(vector, notification_ids, exact_columns)
            grouped_exact_candidates = _group_exact_rows_by_table(exact_candidates)
            vector_candidates: list[Candidate] = []
            candidates = grouped_exact_candidates
        # Không có exact, vector search cho tất cả các label Muc và DongBang
        else:
            exact_candidates = []
            grouped_exact_candidates = []
            vector_candidates = [
                candidate
                for label in CAC_LABEL_THONG_BAO
                for candidate in self._vector_mot_label(label, vector, notification_ids)
            ]
            candidates = vector_candidates

        for candidate in candidates:
            candidate["metadata"].setdefault("exact_columns", exact_columns)
        return ThongBaoRetrievalResult(
            temporal_scope=temporal_scope,
            type_classification=type_classification,
            notification_ids=notification_ids,
            exact_values=exact_columns,
            exact_candidates=exact_candidates,
            grouped_exact_candidates=grouped_exact_candidates,
            vector_candidates=vector_candidates,
            candidates=candidates,
        )
