"""Điều phối riêng toàn bộ pipeline retrieval của miền Thông báo."""
import asyncio
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from app.services.common.candidate import Candidate, build_context
from app.services.common.pipeline_logger import (
    elapsed_ms,
    log_context,
    log_event,
    now,
    summarize_candidates,
)
from app.services.thong_bao.expander import asks_list, expand_notification_candidate
from app.services.thong_bao.retriever import ThongBaoRetriever, select_notification_top_k
from app.services.thong_bao.temporal import MocThoiGian, doc_moc_thoi_gian


logger = logging.getLogger("app.thong_bao")

EmbeddingProvider = Callable[[str], list[float]]
CandidateExpander = Callable[[Candidate, bool, list[float]], list[Candidate]]
QueryNormalizer = Callable[[str], object]


def _shared_embedding_provider(query: str) -> list[float]:
    """Sinh embedding bằng model dùng chung nhưng không làm pipeline phụ thuộc ChatService."""
    from app.services.common.embedding import get_embedding_model

    embeddings = get_embedding_model().get_embedding_batch([query])
    return embeddings[0] if embeddings else []


@dataclass(frozen=True)
class ThongBaoPipelineResult:
    """Kết quả từng tầng để ChatService và file debug có thể quan sát thống nhất."""

    vector: list[float]
    candidates: list[Candidate]
    selected_candidates: list[Candidate]
    expanded_candidates: list[Candidate]
    context: str
    original_query: str = ""
    normalized_query: str = ""
    asks_list: bool = False
    temporal_scope: MocThoiGian = field(default_factory=MocThoiGian)
    notice_type: str | None = None
    notice_type_signals: tuple[str, ...] = ()
    notification_ids: list[str] = field(default_factory=list)
    exact_values: dict[str, list[str]] = field(default_factory=dict)
    exact_candidates: list[Candidate] = field(default_factory=list)
    grouped_exact_candidates: list[Candidate] = field(default_factory=list)
    vector_candidates: list[Candidate] = field(default_factory=list)


class ThongBaoPipeline:
    """Chạy embedding, retrieval, ranking, expansion và context cho THONG_BAO."""

    def __init__(
        self,
        *,
        retriever: ThongBaoRetriever | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        candidate_expander: CandidateExpander | None = None,
        query_normalizer: QueryNormalizer | None = None,
    ) -> None:
        """Cho phép thay dependency khi test nhưng mặc định dùng toàn bộ service thật."""
        self._retriever = retriever or ThongBaoRetriever()
        self._embedding_provider = embedding_provider or _shared_embedding_provider
        self._candidate_expander = candidate_expander or expand_notification_candidate
        if query_normalizer is None:
            from app.services.thong_bao.query_normalizer import normalize_notification_query

            query_normalizer = normalize_notification_query
        self._query_normalizer = query_normalizer

    async def run(
        self,
        query: str,
        *,
        top_k: int = 6,
        max_context_chars: int = 12000,
    ) -> ThongBaoPipelineResult:
        """Chạy tuần tự các tầng chính và song song expansion của các candidate đã chọn."""
        total_started = now()
        original_query = (query or "").strip()
        if not original_query:
            raise ValueError("Câu hỏi debug Thông báo không được để trống")
        if top_k <= 0:
            raise ValueError("top_k phải lớn hơn 0")
        if max_context_chars <= 0:
            raise ValueError("max_context_chars phải lớn hơn 0")

        normalize_started = now()
        applied_rules: list[dict[str, str]] = []
        try:
            normalization = self._query_normalizer(original_query)
            if inspect.isawaitable(normalization):
                normalization = await normalization

            if isinstance(normalization, dict):
                normalized_query = str(
                    normalization.get("normalized_query") or ""
                ).strip()
                rules = normalization.get("applied_rules")
                if isinstance(rules, list):
                    applied_rules = [
                        item for item in rules if isinstance(item, dict)
                    ]
            else:
                # Giữ compatibility với dependency injection/test cũ trả thẳng string.
                normalized_query = str(normalization or "").strip()
        except Exception as exc:
            logger.warning("[thong_bao][normalizer] fallback query gốc: %s", exc)
            normalized_query = ""

        normalized_query = normalized_query or original_query
        log_event(
            "THONG_BAO",
            "normalize",
            original_query=original_query,
            normalized_query=normalized_query,
            applied_rules=applied_rules,
            elapsed_ms=elapsed_ms(normalize_started),
        )

        embedding_started = now()
        vector = await asyncio.to_thread(self._embedding_provider, normalized_query)
        list_requested = asks_list(normalized_query)
        log_event(
            "THONG_BAO",
            "embedding",
            vector_size=len(vector),
            asks_list=list_requested,
            elapsed_ms=elapsed_ms(embedding_started),
        )
        if not vector:
            logger.warning("[thong_bao][embedding] Không tạo được vector cho query=%s", normalized_query)
            empty_context = build_context([], max_chars=max_context_chars)
            log_context("THONG_BAO", empty_context)
            log_event("THONG_BAO", "done", total_ms=elapsed_ms(total_started))
            return ThongBaoPipelineResult(
                vector=[],
                candidates=[],
                selected_candidates=[],
                expanded_candidates=[],
                context=empty_context,
                original_query=original_query,
                normalized_query=normalized_query,
                asks_list=list_requested,
                temporal_scope=doc_moc_thoi_gian(normalized_query),
            )

        retrieval_started = now()
        retrieval = await asyncio.to_thread(
            self._retriever.retrieve_with_trace,
            normalized_query,
            vector,
        )
        candidates = retrieval.candidates
        log_event(
            "THONG_BAO",
            "retrieval",
            temporal_scope=retrieval.temporal_scope,
            notice_type=retrieval.type_classification.notice_type,
            notice_type_signals=retrieval.type_classification.matched_signals,
            notice_type_ambiguous=retrieval.type_classification.ambiguous_types,
            notification_ids=retrieval.notification_ids,
            exact_values=retrieval.exact_values,
            exact_candidates=summarize_candidates(retrieval.exact_candidates),
            grouped_exact_candidates=summarize_candidates(retrieval.grouped_exact_candidates),
            vector_candidates=summarize_candidates(retrieval.vector_candidates),
            candidates_before_top_k=summarize_candidates(candidates),
            elapsed_ms=elapsed_ms(retrieval_started),
        )

        ranking_started = now()
        selected_candidates = select_notification_top_k(candidates, top_k)
        log_event(
            "THONG_BAO",
            "ranking_top_k",
            top_k=top_k,
            selected=summarize_candidates(selected_candidates),
            elapsed_ms=elapsed_ms(ranking_started),
        )

        expansion_started = now()
        expansion_groups = await asyncio.gather(
            *[
                asyncio.to_thread(
                    self._candidate_expander,
                    candidate,
                    list_requested,
                    vector,
                )
                for candidate in selected_candidates
            ],
            return_exceptions=True,
        )
        expanded_candidates: list[Candidate] = []
        expansion_errors = 0
        for group in expansion_groups:
            if isinstance(group, Exception):
                expansion_errors += 1
                logger.warning("[thong_bao][expansion] Bỏ qua candidate lỗi: %s", group)
                continue
            expanded_candidates.extend(group)
        log_event(
            "THONG_BAO",
            "expansion",
            seed_count=len(selected_candidates),
            expanded_count=len(expanded_candidates),
            errors=expansion_errors,
            expanded=summarize_candidates(expanded_candidates),
            elapsed_ms=elapsed_ms(expansion_started),
        )

        context_started = now()
        context_candidates = [*selected_candidates, *expanded_candidates]
        context = build_context(context_candidates, max_chars=max_context_chars)
        log_event(
            "THONG_BAO",
            "context_build",
            candidate_count=len(context_candidates),
            context_chars=len(context),
            elapsed_ms=elapsed_ms(context_started),
        )
        log_context("THONG_BAO", context)
        log_event("THONG_BAO", "done", total_ms=elapsed_ms(total_started))
        return ThongBaoPipelineResult(
            vector=vector,
            candidates=candidates,
            selected_candidates=selected_candidates,
            expanded_candidates=expanded_candidates,
            context=context,
            original_query=original_query,
            normalized_query=normalized_query,
            asks_list=list_requested,
            temporal_scope=retrieval.temporal_scope,
            notice_type=retrieval.type_classification.notice_type,
            notice_type_signals=retrieval.type_classification.matched_signals,
            notification_ids=retrieval.notification_ids,
            exact_values=retrieval.exact_values,
            exact_candidates=retrieval.exact_candidates,
            grouped_exact_candidates=retrieval.grouped_exact_candidates,
            vector_candidates=retrieval.vector_candidates,
        )
