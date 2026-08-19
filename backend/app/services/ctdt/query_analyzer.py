"""Phân tích truy vấn CTĐT, tách nguyên logic khỏi ChatService của Linh."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from app.services.common.llm_service import MODEL_PRIMARY_9B, call_model_json
from app.services.ctdt.schema import GRAPH_SCHEMA

_ALLOWED_VECTOR_TARGETS = {"HocPhan", "DieuKienTotNghiep", "ChuanDauRa", "VanBanPhapLy"}
_ALLOWED_GRAPH_RELATIONS = {
    "BAN_HANH_THEO", "DAO_TAO", "THUOC_VE", "CAP", "CO", "THAM_KHAO",
    "DAT_DUOC", "YEU_CAU", "GOM", "DOI_VOI", "YEU_CAU_TIEN_QUYET",
    "CO_THE_SONG_HANH",
}
_ALLOWED_ANCHOR_NODE_TYPES = {
    "ChuongTrinhDaoTao", "Nganh", "KhoiKienThuc", "HocPhan", "ChuanDauRa",
    "DieuKienTotNghiep", "VanBanPhapLy", "Khoa", "BoMon",
}
_ALLOWED_ANSWER_SHAPES = {"single", "list", "path", "summary"}


def normalize_history(history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    cleaned: List[Dict[str, str]] = []
    for message in (history or [])[-8:]:
        role = str(message.get("role", "user")).strip().lower()
        content = str(message.get("content", "")).strip()
        if role not in {"user", "assistant"}:
            role = "user"
        if content:
            cleaned.append({"role": role, "content": content})
    return cleaned


def history_text(history: List[Dict[str, str]]) -> str:
    return "\n".join(f"{item['role']}: {item['content']}" for item in history)


def _normalize_query_type(value: str) -> str:
    query_type = (value or "").strip().lower()
    if query_type in {"attribute", "relation", "path", "aggregation", "description", "list"}:
        return query_type
    return "description"


def _normalize_ctdt_filters(raw_filters: Dict[str, Any]) -> Dict[str, Any]:
    filters = raw_filters if isinstance(raw_filters, dict) else {}
    normalized: Dict[str, Any] = {}

    khoa_raw = filters.get("khoa")
    khoa_value: Any = None
    if isinstance(khoa_raw, int):
        khoa_value = khoa_raw
    elif isinstance(khoa_raw, str):
        digits = re.findall(r"\d+", khoa_raw)
        if digits:
            try:
                khoa_value = int(digits[0])
            except ValueError:
                khoa_value = None
    if khoa_value is not None:
        normalized["khoa"] = khoa_value

    he_raw = filters.get("he")
    if isinstance(he_raw, str):
        he_value = he_raw.strip()
        if he_value:
            normalized["he"] = he_value
    return normalized


def _normalize_graph_plan(
    raw_plan: Any,
    entities: List[Dict[str, str]],
    relations: List[str],
    query_type: str,
    constraints: Dict[str, Any],
) -> Dict[str, Any]:
    plan = raw_plan if isinstance(raw_plan, dict) else {}

    raw_anchor_types = plan.get("anchor_node_types") if isinstance(plan.get("anchor_node_types"), list) else []
    anchor_node_types = [
        str(item).strip()
        for item in raw_anchor_types
        if str(item).strip() in _ALLOWED_ANCHOR_NODE_TYPES
    ]
    if not anchor_node_types:
        for entity in entities:
            entity_type = str(entity.get("type", "")).strip()
            if entity_type in _ALLOWED_ANCHOR_NODE_TYPES and entity_type not in anchor_node_types:
                anchor_node_types.append(entity_type)

    raw_focus_relations = plan.get("focus_relations") if isinstance(plan.get("focus_relations"), list) else []
    focus_relations = [
        str(item).strip().upper()
        for item in raw_focus_relations
        if str(item).strip().upper() in _ALLOWED_GRAPH_RELATIONS
    ]
    if not focus_relations:
        focus_relations = [relation for relation in relations if relation in _ALLOWED_GRAPH_RELATIONS]

    raw_expansion = plan.get("expansion_policy") if isinstance(plan.get("expansion_policy"), dict) else {}
    max_depth = raw_expansion.get("max_depth", constraints.get("depth", 2))
    max_paths = raw_expansion.get("max_paths", 60)
    max_nodes = raw_expansion.get("max_nodes", 70)
    try:
        max_depth = int(max_depth)
    except (TypeError, ValueError):
        max_depth = 2
    try:
        max_paths = int(max_paths)
    except (TypeError, ValueError):
        max_paths = 60
    try:
        max_nodes = int(max_nodes)
    except (TypeError, ValueError):
        max_nodes = 70

    answer_shape = str(plan.get("answer_shape", "")).strip().lower()
    if answer_shape not in _ALLOWED_ANSWER_SHAPES:
        if query_type == "path":
            answer_shape = "path"
        elif query_type in {"list", "relation"}:
            answer_shape = "list"
        elif query_type in {"attribute", "aggregation"}:
            answer_shape = "single"
        else:
            answer_shape = "summary"

    return {
        "anchor_node_types": anchor_node_types[:3],
        "focus_relations": focus_relations[:4],
        "expansion_policy": {
            "max_depth": max(1, min(max_depth, 2)),
            "max_paths": max(10, min(max_paths, 120)),
            "max_nodes": max(20, min(max_nodes, 120)),
        },
        "answer_shape": answer_shape,
    }


def _normalize_analysis_payload(raw: Dict[str, Any], query: str) -> Dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    rewrite = str(data.get("rewrite") or data.get("rewritten_query") or query).strip() or query

    entities = data.get("entities") if isinstance(data.get("entities"), list) else []
    cleaned_entities: List[Dict[str, str]] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity_type = str(entity.get("type", "")).strip()
        entity_value = str(entity.get("value", "")).strip()
        if entity_type or entity_value:
            cleaned_entities.append({"type": entity_type, "value": entity_value})

    relations = data.get("relations") if isinstance(data.get("relations"), list) else []
    cleaned_relations = [str(item).strip().upper() for item in relations if str(item).strip()]
    constraints = data.get("constraints") if isinstance(data.get("constraints"), dict) else {}
    ctdt_filters = _normalize_ctdt_filters(
        data.get("ctdt_filters") if isinstance(data.get("ctdt_filters"), dict) else {}
    )

    vector_targets = data.get("vector_targets") if isinstance(data.get("vector_targets"), list) else []
    cleaned_vector_targets = [
        str(item).strip()
        for item in vector_targets
        if str(item).strip() in _ALLOWED_VECTOR_TARGETS
    ][:2]

    query_type = _normalize_query_type(str(data.get("query_type", "")).strip())
    graph_plan = _normalize_graph_plan(
        data.get("graph_plan"),
        cleaned_entities,
        cleaned_relations,
        query_type,
        constraints,
    )
    return {
        "rewrite": rewrite,
        "entities": cleaned_entities,
        "relations": cleaned_relations,
        "query_type": query_type,
        "constraints": constraints,
        "ctdt_filters": ctdt_filters,
        "vector_targets": cleaned_vector_targets,
        "graph_plan": graph_plan,
    }


async def analyze_ctdt_query(query: str, history: str = "") -> Dict[str, Any]:
    prompt = f"""
Bạn là chuyên gia phân tích truy vấn CTDT cho hệ thống GraphRAG.
Phải trả về JSON STRICT với format sau:
{{
  "rewrite": "...",
  "entities": [{{"type": "...", "value": "..."}}],
  "relations": ["..."],
  "query_type": "attribute | relation | path | aggregation | description | list",
  "constraints": {{"depth": 2, "limit": 10}},
  "ctdt_filters": {{"khoa": 51, "he": "đại trà"}},
  "vector_targets": ["HocPhan", "DieuKienTotNghiep", "ChuanDauRa", "VanBanPhapLy"],
  "graph_plan": {{
    "anchor_node_types": ["HocPhan", "Nganh", "ChuongTrinhDaoTao"],
    "focus_relations": ["YEU_CAU_TIEN_QUYET", "CO_THE_SONG_HANH", "GOM", "CO", "YEU_CAU", "THUOC_VE"],
    "expansion_policy": {{"max_depth": 2, "max_paths": 60, "max_nodes": 70}},
    "answer_shape": "single | list | path | summary"
  }}
}}

Ràng buộc bắt buộc:
- Chỉ dùng 1 lần gọi LLM.
- rewrite phải là câu hỏi độc lập, rõ nghĩa, dùng lịch sử chat nếu cần.
- entities chỉ chứa thực thể thật xuất hiện hoặc suy ra trực tiếp từ câu hỏi.
- relations chỉ lấy từ schema, nếu không chắc thì [].
- query_type chọn đúng 1 giá trị.
- attribute: hỏi một thuộc tính cụ thể của một thực thể.
- relation: hỏi các thực thể liên quan qua một quan hệ.
- path: hỏi đường đi/chuỗi quan hệ.
- aggregation: thống kê tổng hợp nhiều bản ghi, không dùng cho thuộc tính đơn lẻ.
- description: mô tả chung, chưa đủ tín hiệu cho nhánh cụ thể.
- list: yêu cầu liệt kê danh sách.
- Với "tổng số tín chỉ cần hoàn thành của CTDT", ưu tiên query_type="attribute" và thuộc tính ct.tong_tin_chi.
- constraints chỉ điền khi thực sự cần; nếu không có thì {{}}.
- ctdt_filters chỉ chứa giá trị được nêu rõ; KHÔNG tự thêm default khoa/he.
- vector_targets chỉ chọn trong: HocPhan, DieuKienTotNghiep, ChuanDauRa, VanBanPhapLy.
- Nếu không chắc thì vector_targets = [].
- graph_plan phải tương thích schema.

Schema:
{GRAPH_SCHEMA}

History:
{history or "[empty]"}

Query:
{query}
"""
    raw = await call_model_json(MODEL_PRIMARY_9B, prompt, num_predict=768)
    normalized = _normalize_analysis_payload(raw, query)
    if not normalized.get("vector_targets"):
        normalized["vector_targets"] = []
    return normalized
