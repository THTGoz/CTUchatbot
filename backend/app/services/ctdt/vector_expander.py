"""Graph expansion 1-hop từ các candidate vector của CTĐT."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from app.db.neo4j import get_driver


_ALLOWED_COURSE_RELATIONS = {"YEU_CAU_TIEN_QUYET", "CO_THE_SONG_HANH"}
_RELATION_DISPLAY = {
    "YEU_CAU_TIEN_QUYET": "Yêu cầu tiên quyết",
    "CO_THE_SONG_HANH": "Có thể song hành",
}


def _resolve_course_relations(query: str, relations: List[str]) -> List[str]:
    resolved: List[str] = []
    for relation in relations or []:
        rel = str(relation or "").strip().upper()
        if rel in _ALLOWED_COURSE_RELATIONS and rel not in resolved:
            resolved.append(rel)

    if resolved:
        return resolved

    lowered = str(query or "").casefold()
    if "tiên quyết" in lowered:
        resolved.append("YEU_CAU_TIEN_QUYET")
    if "song hành" in lowered:
        resolved.append("CO_THE_SONG_HANH")
    return resolved


def _expand_one_course(origin_id: str, relations: List[str]) -> List[Dict[str, Any]]:
    if not origin_id or not relations:
        return []

    rel_pattern = "|".join(relations)
    cypher = f"""
    MATCH (h:HocPhan {{id: $origin_id}})-[r:{rel_pattern}]->(target:HocPhan)
    RETURN target.id AS node_id,
           'HocPhan' AS label,
           type(r) AS relationship_type,
           coalesce(target.text, target.ten_hoc_phan, '') AS text,
           coalesce(target.ten_hoc_phan, '') AS title,
           coalesce(target.ma_hoc_phan, target.id, '') AS ma_hoc_phan,
           target.so_tin_chi AS so_tin_chi
    ORDER BY type(r), target.id
    """
    with get_driver().session() as session:
        return session.run(cypher, origin_id=origin_id).data()


def expand_vector_candidates(
    candidates: List[Dict[str, Any]],
    query: str,
    relations: List[str],
    *,
    max_per_origin: int = 4,
    max_total: int = 12,
) -> List[Dict[str, Any]]:
    """Expand candidate HocPhan theo relation intent và giữ provenance origin."""
    course_relations = _resolve_course_relations(query, relations)
    if not course_relations:
        return []

    expanded: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for candidate in candidates:
        if len(expanded) >= max_total:
            break
        if str(candidate.get("label") or "") != "HocPhan":
            continue

        origin_id = str(candidate.get("node_id") or "").strip()
        if not origin_id:
            continue

        rows = _expand_one_course(origin_id, course_relations)
        added = 0
        for row in rows:
            if added >= max_per_origin or len(expanded) >= max_total:
                break
            node_id = str(row.get("node_id") or "").strip()
            relationship = str(row.get("relationship_type") or "").strip()
            key = (origin_id, relationship, node_id)
            if not node_id or key in seen:
                continue
            seen.add(key)
            expanded.append({
                **row,
                "origin": "vector_graph_expansion",
                "origin_node_id": origin_id,
                "origin_cosine_score": candidate.get("cosine_score"),
                "expansion_depth": 1,
            })
            added += 1

    return expanded


def format_vector_expansions(expanded: List[Dict[str, Any]]) -> str:
    """Format expansion theo origin để LLM biết quan hệ thuộc candidate nào."""
    if not expanded:
        return ""

    grouped: dict[str, list[Dict[str, Any]]] = defaultdict(list)
    for row in expanded:
        grouped[str(row.get("origin_node_id") or "")].append(row)

    lines = ["[VECTOR GRAPH EXPANSION]"]
    for origin_id, rows in grouped.items():
        lines.append(f"- Từ học phần {origin_id}:")
        for row in rows:
            relation = str(row.get("relationship_type") or "")
            relation_display = _RELATION_DISPLAY.get(relation, relation)
            node_id = str(row.get("node_id") or "")
            title = str(row.get("title") or row.get("text") or "").strip()
            lines.append(f"  - {relation_display} | {node_id}: {title}")
    return "\n".join(lines)
