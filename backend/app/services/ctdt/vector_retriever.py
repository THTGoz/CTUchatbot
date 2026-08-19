"""Vector fallback của CTĐT, trả candidate có cấu trúc để có thể graph-expand."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List

from app.db.neo4j import get_driver
from app.services.common.embedding import get_embedding_model

logger = logging.getLogger("app.ctdt.vector")

ALLOWED_VECTOR_TARGETS = {"HocPhan", "DieuKienTotNghiep", "ChuanDauRa", "VanBanPhapLy"}
_VECTOR_INDEX_CANDIDATES = {
    "HocPhan": ["vector_hocphan_embedding"],
    "DieuKienTotNghiep": ["vector_dieukientotnghiep_embedding"],
    "ChuanDauRa": ["vector_chuandaura_embedding"],
    "VanBanPhapLy": ["vector_vanbanphaply_embedding"],
}


def _stringify(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _strip_embedding(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_embedding(item)
            for key, item in value.items()
            if str(key).lower() != "embedding"
        }
    if isinstance(value, list):
        return [_strip_embedding(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_strip_embedding(item) for item in value)
    return value


def _execute_vector_query(index_name: str, embedding: List[float], top_k: int = 3) -> List[Dict[str, Any]]:
    cypher = (
        f"CALL db.index.vector.queryNodes('{index_name}', $top_k, $embedding) "
        "YIELD node, score "
        "RETURN labels(node) AS labels, properties(node) AS node, score "
        "ORDER BY score DESC "
        "LIMIT $top_k"
    )
    with get_driver().session() as session:
        return session.run(cypher, embedding=embedding, top_k=top_k).data()


def _row_to_candidate(target: str, row: Dict[str, Any], index_name: str) -> Dict[str, Any]:
    sanitized = _strip_embedding(row)
    props = sanitized.get("node") if isinstance(sanitized.get("node"), dict) else {}
    labels = sanitized.get("labels") if isinstance(sanitized.get("labels"), list) else []
    label = target if target in labels or not labels else str(labels[0])
    node_id = str(props.get("id") or props.get("ma_hoc_phan") or "").strip()
    return {
        "origin": "vector",
        "target": target,
        "label": label,
        "node_id": node_id,
        "index_name": index_name,
        "cosine_score": float(sanitized.get("score") or 0.0),
        "labels": labels,
        "properties": props,
    }


def format_vector_candidates(target: str, candidates: List[Dict[str, Any]]) -> str:
    if not candidates:
        return ""
    index_name = str(candidates[0].get("index_name") or "")
    lines = [f"- {target} [{index_name}]" if index_name else f"- {target}"]
    for index, candidate in enumerate(candidates, 1):
        lines.append(
            f"  {index}. score={candidate.get('cosine_score')} "
            f"labels={_stringify(candidate.get('labels', []))} "
            f"node={_stringify(candidate.get('properties', {}))}"
        )
    return "\n".join(lines)


async def search_vector_candidates(query: str, target: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Vector search và trả candidate để pipeline có thể expand tiếp trên graph."""
    if target not in ALLOWED_VECTOR_TARGETS:
        return []

    try:
        embedding_batch = await asyncio.to_thread(get_embedding_model().get_embedding_batch, [query])
        if not embedding_batch:
            return []
        embedding = embedding_batch[0]
    except Exception as exc:
        logger.warning("[CTDT vector] embedding failed target=%s error=%s", target, exc)
        return []

    for index_name in _VECTOR_INDEX_CANDIDATES.get(target, []):
        try:
            rows = await asyncio.to_thread(_execute_vector_query, index_name, embedding, top_k)
        except Exception as exc:
            logger.info("[CTDT vector] index=%s unavailable target=%s error=%s", index_name, target, exc)
            continue
        if rows:
            return [_row_to_candidate(target, row, index_name) for row in rows]
    return []


async def search_vector_target(query: str, target: str, top_k: int = 3) -> str:
    """API cũ: vẫn trả text context để không làm hỏng call-site khác."""
    candidates = await search_vector_candidates(query, target, top_k=top_k)
    return format_vector_candidates(target, candidates)
