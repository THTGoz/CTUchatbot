"""Luồng CTĐT của Linh với normalization + vector-seed graph expansion."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from app.services.common.llm_service import call_model_9b
from app.services.common.pipeline_logger import elapsed_ms, log_context, log_event, now
from app.services.ctdt.query_analyzer import analyze_ctdt_query, history_text, normalize_history
from app.services.ctdt.query_normalizer import normalize_ctdt_query
from app.services.ctdt.subgraph_retriever import GraphBuildResult, SubgraphRetriever
from app.services.ctdt.vector_expander import expand_vector_candidates, format_vector_expansions
from app.services.ctdt.vector_retriever import (
    ALLOWED_VECTOR_TARGETS,
    format_vector_candidates,
    search_vector_candidates,
)

logger = logging.getLogger("app.ctdt")


@dataclass(frozen=True)
class CTDTPipelineResult:
    answer: str
    context: str
    rewritten_query: str
    analysis: Dict[str, Any]
    graph_context: str
    vector_context: str
    metadata: Dict[str, Any]
    used_default_ctdt: bool


def _format_hybrid_context(graph_context: str, vector_context: str) -> str:
    graph_section = graph_context.strip() or "[GRAPH RESULT]\nKhông có kết quả graph."
    vector_section = vector_context.strip() or "[VECTOR RESULT]\nKhông có kết quả vector."
    return f"{graph_section}\n\n{vector_section}"


class CTDTPipeline:
    def __init__(self) -> None:
        self.subgraph_retriever = SubgraphRetriever()

    async def _retrieve_hybrid_context(
        self,
        query: str,
        graph_result: GraphBuildResult,
        vector_targets: List[str],
        relations: List[str],
    ) -> tuple[str, str]:
        graph_context = graph_result.graph_text.strip() or "[GRAPH RESULT]\nKhông có dữ liệu phù hợp."
        selected_targets = vector_targets if vector_targets else ["HocPhan", "DieuKienTotNghiep"]

        vector_started = now()
        candidate_groups: list[tuple[str, list[dict[str, Any]]]] = []

        if not graph_result.is_graph_sufficient and selected_targets:
            valid_targets = [target for target in selected_targets if target in ALLOWED_VECTOR_TARGETS]
            results = await asyncio.gather(*[
                search_vector_candidates(query, target, top_k=3)
                for target in valid_targets
            ])
            candidate_groups = [
                (target, candidates)
                for target, candidates in zip(valid_targets, results)
                if candidates
            ]

        all_candidates = [
            candidate
            for _, candidates in candidate_groups
            for candidate in candidates
        ]

        expanded = []
        if all_candidates:
            expanded = await asyncio.to_thread(
                expand_vector_candidates,
                all_candidates,
                query,
                relations,
            )

        direct_sections = [
            format_vector_candidates(target, candidates)
            for target, candidates in candidate_groups
        ]
        direct_sections = [section for section in direct_sections if section]
        expansion_section = format_vector_expansions(expanded)

        vector_parts = direct_sections + ([expansion_section] if expansion_section else [])
        vector_context = (
            "[VECTOR RESULT]\n" + "\n\n".join(vector_parts)
            if vector_parts
            else "[VECTOR RESULT]\nKhông có kết quả vector."
        )

        log_event(
            "CTDT",
            "vector_retrieval",
            executed=not graph_result.is_graph_sufficient and bool(selected_targets),
            targets=selected_targets,
            result_sections=len(direct_sections),
            candidate_count=len(all_candidates),
            expanded_count=len(expanded),
            elapsed_ms=elapsed_ms(vector_started),
        )
        return graph_context, vector_context

    async def _generate_answer(
        self,
        original_query: str,
        rewritten_query: str,
        context: str,
        used_default_ctdt: bool,
    ) -> str:
        default_note = (
            "Hệ thống đã áp dụng mặc định CTĐT: khoa=51, he=đại trà."
            if used_default_ctdt
            else "[Không dùng default CTĐT]"
        )
        prompt = f"""
Bạn là trợ lý tư vấn học vụ bằng tiếng Việt cho hệ thống GraphRAG.

Nhiệm vụ:
1. Xác định đúng dữ liệu trong context cần cho câu hỏi.
2. Trả lời trực tiếp bằng tiếng Việt.

Quy tắc:
- Chỉ trả lời phần được hỏi, không tóm tắt toàn bộ graph/context.
- Câu hỏi đơn giản: ưu tiên 1-3 câu ngắn.
- Chỉ dùng bullet khi có nhiều học phần, nhiều điều kiện hoặc nhiều trường hợp cần liệt kê.
- Không lặp lại các property/quan hệ không cần thiết cho câu trả lời.
- Không bịa thông tin ngoài context.
- GRAPH RESULT là bằng chứng trực tiếp từ graph.
- VECTOR RESULT dùng để xác định candidate; nếu có VECTOR GRAPH EXPANSION thì các quan hệ trong phần đó là bằng chứng graph 1-hop và được dùng để trả lời.
- Không tự suy ra quan hệ chỉ từ similarity score của vector candidate.
- Nếu context chưa đủ, nói ngắn gọn phần thông tin còn thiếu.
- Nếu có default CTĐT đã được dùng và việc đó ảnh hưởng câu trả lời, nhắc một lần thật ngắn.
- Không thêm lời mời hỏi tiếp hoặc diễn giải ngoài yêu cầu.

Thông tin bổ sung:
{default_note}

Câu hỏi gốc:
{original_query}

Câu hỏi đã chuẩn hóa:
{rewritten_query}

Context:
{context}

Trả lời ngắn gọn, chính xác, đúng trọng tâm và chỉ dùng thông tin trong context.
"""
        return (await call_model_9b(prompt, temperature=0.2, num_predict=256)).strip()

    async def handle_query(self, query: str, history: List[Dict[str, Any]]) -> CTDTPipelineResult:
        total_started = now()
        cleaned_history = normalize_history(history)
        history_string = history_text(cleaned_history)

        normalization = normalize_ctdt_query(query)
        normalized_query = normalization["normalized_query"] or query
        log_event(
            "CTDT",
            "normalization",
            original_query=query,
            normalized_query=normalized_query,
            applied_rules=normalization["applied_rules"],
        )

        analysis_started = now()
        analysis = await analyze_ctdt_query(normalized_query, history_string)
        rewrite_normalization = normalize_ctdt_query(analysis.get("rewrite", normalized_query))
        rewritten_query = rewrite_normalization["normalized_query"] or normalized_query
        analysis["rewrite"] = rewritten_query
        vector_targets = analysis.get("vector_targets", []) or ["HocPhan", "DieuKienTotNghiep"]
        relations = analysis.get("relations", []) if isinstance(analysis.get("relations"), list) else []
        log_event(
            "CTDT",
            "analysis",
            original_query=query,
            normalized_query=normalized_query,
            rewritten_query=rewritten_query,
            analysis=analysis,
            elapsed_ms=elapsed_ms(analysis_started),
        )

        retrieval_analysis = dict(analysis)
        retrieval_analysis["query"] = normalized_query
        graph_started = now()
        graph_result = await asyncio.to_thread(self.subgraph_retriever.retrieve, retrieval_analysis)
        log_event(
            "CTDT",
            "graph_retrieval",
            sufficient=graph_result.is_graph_sufficient,
            used_default_ctdt=graph_result.used_default_ctdt,
            metadata=graph_result.metadata,
            elapsed_ms=elapsed_ms(graph_started),
        )

        graph_context, vector_context = await self._retrieve_hybrid_context(
            rewritten_query,
            graph_result,
            vector_targets,
            relations,
        )
        context = _format_hybrid_context(graph_context, vector_context)
        log_context("CTDT", context)

        generation_started = now()
        answer = await self._generate_answer(
            original_query=query,
            rewritten_query=rewritten_query,
            context=context,
            used_default_ctdt=graph_result.used_default_ctdt,
        )
        log_event("CTDT", "generation", elapsed_ms=elapsed_ms(generation_started))
        log_event("CTDT", "done", total_ms=elapsed_ms(total_started))
        return CTDTPipelineResult(
            answer=answer,
            context=context,
            rewritten_query=rewritten_query,
            analysis=analysis,
            graph_context=graph_context,
            vector_context=vector_context,
            metadata=graph_result.metadata,
            used_default_ctdt=graph_result.used_default_ctdt,
        )


ctdt_pipeline = CTDTPipeline()
