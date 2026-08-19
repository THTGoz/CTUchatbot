"""Điều phối tối giản: router -> đúng một pipeline domain -> answer."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from app.services.common.llm_service import LLMService
from app.services.common.pipeline_logger import elapsed_ms, log_answer, log_event, now
from app.services.ctdt.pipeline import ctdt_pipeline
from app.services.qchv.quyche_service import quyche_service
from app.services.thong_bao.pipeline import ThongBaoPipeline

logger = logging.getLogger("app.orchestrator")


def _normalize_history(history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    cleaned: List[Dict[str, str]] = []
    for message in (history or [])[-8:]:
        role = str(message.get("role", "user")).strip().lower()
        content = str(message.get("content", "")).strip()
        if role not in {"user", "assistant"}:
            role = "user"
        if content:
            cleaned.append({"role": role, "content": content})
    return cleaned


def _history_text(history: List[Dict[str, str]]) -> str:
    return "\n".join(f"{item['role']}: {item['content']}" for item in history)


class ChatOrchestrator:
    def __init__(self) -> None:
        self.llm = LLMService()
        self.thong_bao = ThongBaoPipeline()

    async def handle_query(self, query: str, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_started = now()
        question = (query or "").strip()
        cleaned_history = _normalize_history(history)
        history_string = _history_text(cleaned_history)
        log_event(
            "CHAT",
            "request",
            original_query=question,
            history_count=len(cleaned_history),
        )

        if not question:
            llm_started = now()
            answer = await self.llm.generate_without_query(question, history_string)
            log_event("SOCIAL", "llm", elapsed_ms=elapsed_ms(llm_started))
            log_answer("SOCIAL", answer)
            log_event("CHAT", "done", domain="SOCIAL", total_ms=elapsed_ms(total_started))
            return {"answer": answer, "domain": "SOCIAL", "debug": {"reason": "empty_query"}}

        router_started = now()
        domain = await self.llm.classify_domain(question, history_string)
        router_ms = elapsed_ms(router_started)
        logger.info("[router] query=%r domain=%s", question, domain)
        log_event("ROUTER", "result", domain=domain, elapsed_ms=router_ms)

        if domain == "SOCIAL":
            llm_started = now()
            answer = await self.llm.generate_without_query(question, history_string)
            log_event("SOCIAL", "llm", elapsed_ms=elapsed_ms(llm_started))
            log_answer(domain, answer)
            log_event("CHAT", "done", domain=domain, total_ms=elapsed_ms(total_started))
            return {"answer": answer, "domain": domain, "debug": {}}

        if domain == "QCHV":
            result = await quyche_service.handle_query(question, cleaned_history)
            answer = str(result.get("answer", "")).strip()
            log_answer(domain, answer)
            log_event("CHAT", "done", domain=domain, total_ms=elapsed_ms(total_started))
            return {
                "answer": answer,
                "domain": domain,
                "debug": {
                    "vb_id": result.get("vb_id"),
                    "vb_display": result.get("vb_display"),
                    "refs": result.get("refs", []),
                },
            }

        if domain == "CTDT":
            result = await ctdt_pipeline.handle_query(question, cleaned_history)
            log_answer(domain, result.answer)
            log_event("CHAT", "done", domain=domain, total_ms=elapsed_ms(total_started))
            return {
                "answer": result.answer,
                "domain": domain,
                "debug": {
                    "rewritten_query": result.rewritten_query,
                    "analysis": result.analysis,
                    "graph_metadata": result.metadata,
                    "used_default_ctdt": result.used_default_ctdt,
                },
            }

        if domain == "THONG_BAO":
            try:
                top_k = max(1, int(os.getenv("CHAT_GLOBAL_TOP_K", "6")))
            except ValueError:
                top_k = 6
            try:
                max_context_chars = max(1000, int(os.getenv("MAX_CONTEXT_CHARS", "12000")))
            except ValueError:
                max_context_chars = 12000

            result = await self.thong_bao.run(
                question,
                top_k=top_k,
                max_context_chars=max_context_chars,
            )
            generation_started = now()
            answer = await self.llm.generate(result.normalized_query, result.context)
            log_event(
                "THONG_BAO",
                "generation",
                generation_query=result.normalized_query,
                elapsed_ms=elapsed_ms(generation_started),
            )
            log_answer(domain, answer)
            log_event("CHAT", "done", domain=domain, total_ms=elapsed_ms(total_started))
            return {
                "answer": answer,
                "domain": domain,
                "debug": {
                    "normalized_query": result.normalized_query,
                    "temporal_scope": result.temporal_scope.__dict__,
                    "notification_ids": result.notification_ids,
                    "exact_values": result.exact_values,
                    "candidate_count": len(result.candidates),
                    "selected_candidate_count": len(result.selected_candidates),
                },
            }

        raise RuntimeError(f"Router trả domain không hỗ trợ: {domain}")


chat_orchestrator = ChatOrchestrator()
