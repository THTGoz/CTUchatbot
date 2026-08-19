"""Luồng Quy chế học vụ của Hân, đóng gói thành module độc lập.

Thuật toán exact/vector và prompt QCHV được giữ nguyên; chỉ dùng chung Neo4j driver
và embedding singleton của backend để tránh mở kết nối/model trùng lặp.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List

from app.db.neo4j import read_query
from app.services.common.embedding import get_embedding_model
from app.services.common.pipeline_logger import elapsed_ms, log_context, log_event, now
from app.services.qchv.quyche_llm_service import QuyCheLLMService, VANBAN_DISPLAY

logger = logging.getLogger("app.qchv")

ARABIC_TO_ROMAN = {
    1: "I", 2: "II", 3: "III", 4: "IV", 5: "V",
    6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X",
    11: "XI", 12: "XII", 13: "XIII", 14: "XIV", 15: "XV",
}


class Neo4jQuerier:
    def run(self, cypher: str, **params):
        return read_query(cypher, params)

    def get_chuong(self, vb_id: str, roman: str) -> List[str]:
        cid = f"{vb_id}_{self._slugify('Chương ' + roman)}"
        rows = self.run(
            "MATCH (c:Chuong {id:$cid}) RETURN coalesce(c.text_embed, c.ten, '') AS text",
            cid=cid,
        )
        return [r["text"] for r in rows if r.get("text")]

    def get_dieu(self, vb_id: str, dso: str) -> List[str]:
        did = f"{vb_id}_Dieu{dso}"
        rows = self.run(
            """
            MATCH (d:Dieu {id:$did})
            OPTIONAL MATCH (d)-[:co_khoan]->(k:Khoan)
            OPTIONAL MATCH (k)-[:co_diem]->(m:Diem)
            WITH d,
                 collect(DISTINCT coalesce(k.text_embed, k.noi_dung, '')) AS khoan_texts,
                 collect(DISTINCT coalesce(m.text_embed, m.noi_dung, '')) AS diem_texts
            RETURN coalesce(d.text_embed, d.tieu_de, '') AS dieu_text,
                   khoan_texts, diem_texts
            """,
            did=did,
        )
        texts: List[str] = []
        for row in rows:
            if row.get("dieu_text"):
                texts.append(row["dieu_text"])
            texts += [text for text in row.get("khoan_texts", []) if text]
            texts += [text for text in row.get("diem_texts", []) if text]
        return texts

    def get_khoan(self, vb_id: str, dso: str, kso: str) -> List[str]:
        did = f"{vb_id}_Dieu{dso}"
        kid = f"{did}_Khoan{kso}"
        rows = self.run(
            """
            MATCH (k:Khoan {id:$kid})
            OPTIONAL MATCH (k)-[:co_diem]->(m:Diem)
            RETURN coalesce(k.text_embed, k.noi_dung, '') AS khoan_text,
                   collect(coalesce(m.text_embed, m.noi_dung, '')) AS diem_texts
            """,
            kid=kid,
        )
        texts: List[str] = []
        for row in rows:
            if row.get("khoan_text"):
                texts.append(row["khoan_text"])
            texts += [text for text in row.get("diem_texts", []) if text]
        return texts

    def get_diem(self, vb_id: str, dso: str, kso: str, dky: str) -> List[str]:
        did = f"{vb_id}_Dieu{dso}"
        kid = f"{did}_Khoan{kso}"
        mid = f"{kid}_Diem{self._slugify(dky)}"
        rows = self.run(
            "MATCH (m:Diem {id:$mid}) RETURN coalesce(m.text_embed, m.noi_dung, '') AS text",
            mid=mid,
        )
        return [r["text"] for r in rows if r.get("text")]

    def vector_search(self, vb_id: str, query_vec: List[float], top_k: int) -> List[str]:
        results = []
        for index_name in ["dieu_embedding_index", "khoan_embedding_index", "diem_embedding_index"]:
            rows = self.run(
                f"""
                CALL db.index.vector.queryNodes('{index_name}', $top_k, $qvec)
                YIELD node, score
                WHERE node.id STARTS WITH $vb_id
                RETURN node.id AS id,
                       coalesce(node.text_embed, node.noi_dung, node.tieu_de, '') AS text,
                       score
                """,
                qvec=query_vec,
                top_k=top_k,
                vb_id=vb_id,
            )
            for row in rows:
                if row.get("text"):
                    results.append((row["score"], row["text"], row["id"]))

        seen: Dict[str, tuple[float, str]] = {}
        for score, text, node_id in results:
            if node_id not in seen or score > seen[node_id][0]:
                seen[node_id] = (score, text)
        sorted_results = sorted(seen.values(), key=lambda item: item[0], reverse=True)[:top_k]
        return [text for _, text in sorted_results]

    @staticmethod
    def _slugify(text: str) -> str:
        if not text:
            return ""
        import unicodedata

        text = text.replace("Đ", "D").replace("đ", "d")
        nfkd = unicodedata.normalize("NFKD", text)
        text = "".join(character for character in nfkd if not unicodedata.combining(character))
        return re.sub(r"[^a-zA-Z0-9]", "", text)


class QuyCheService:
    def __init__(self) -> None:
        self.querier = Neo4jQuerier()
        self.llm_service = QuyCheLLMService()

    def _embed_text(self, text: str) -> List[float]:
        try:
            vectors = get_embedding_model().get_embedding_batch([text])
            return vectors[0] if vectors else []
        except Exception as exc:
            logger.warning("[QCHV] Embedding error: %s", exc)
            return []

    def _extract_references(self, question: str) -> List[Dict[str, str]]:
        refs: List[Dict[str, str]] = []
        for match in re.finditer(r"[Cc]h[ưu]ơng\s+([IVXLCDM]+|\d+)", question):
            value = match.group(1)
            if value.isdigit():
                value = self._arabic_to_roman(int(value))
            refs.append({"type": "chuong", "value": value})

        for match in re.finditer(
            r"[Đđ]i[eềếệ]u\s+(\d+).*?[Kk]ho[aả]n\s+(\d+).*?[Đđ]i[eể]m\s+([a-zđ])",
            question,
            re.IGNORECASE,
        ):
            refs.append({
                "type": "diem",
                "dieu": match.group(1),
                "khoan": match.group(2),
                "diem": match.group(3),
            })

        for match in re.finditer(
            r"[Đđ]i[eềếệ]u\s+(\d+).*?[Kk]ho[aả]n\s+(\d+)",
            question,
            re.IGNORECASE,
        ):
            if not any(
                ref["type"] == "diem"
                and ref["dieu"] == match.group(1)
                and ref["khoan"] == match.group(2)
                for ref in refs
            ):
                refs.append({"type": "khoan", "dieu": match.group(1), "khoan": match.group(2)})

        for match in re.finditer(r"[Đđ]i[eềếệ]u\s+(\d+)", question, re.IGNORECASE):
            dso = match.group(1)
            if not any(ref.get("dieu") == dso for ref in refs):
                refs.append({"type": "dieu", "dieu": dso})
        return refs

    def _arabic_to_roman(self, number: int) -> str:
        return ARABIC_TO_ROMAN.get(number, str(number))

    def _collect_context(self, vb_id: str, question: str, refs: List[Dict[str, str]]) -> str:
        started = now()
        texts: List[str] = []
        retrieval_mode = "exact" if refs else "vector"
        if refs:
            for ref in refs:
                if ref["type"] == "chuong":
                    texts += self.querier.get_chuong(vb_id, ref["value"])
                elif ref["type"] == "dieu":
                    texts += self.querier.get_dieu(vb_id, ref["dieu"])
                elif ref["type"] == "khoan":
                    texts += self.querier.get_khoan(vb_id, ref["dieu"], ref["khoan"])
                elif ref["type"] == "diem":
                    texts += self.querier.get_diem(vb_id, ref["dieu"], ref["khoan"], ref["diem"])
        else:
            vector = self._embed_text(question)
            if vector:
                texts = self.querier.vector_search(
                    vb_id,
                    vector,
                    top_k=int(os.getenv("QUYCHE_VECTOR_TOP_K", "6")),
                )
            else:
                logger.warning("[QCHV] Không lấy được embedding")

        unique: List[str] = []
        seen = set()
        for text in texts:
            if text and text not in seen:
                seen.add(text)
                unique.append(text)
        context = "\n\n---\n\n".join(unique)
        log_event(
            "QCHV",
            "retrieval",
            mode=retrieval_mode,
            vb_id=vb_id,
            refs=refs,
            result_count=len(unique),
            context_chars=len(context),
            elapsed_ms=elapsed_ms(started),
        )
        return context

    async def handle_query(self, query: str, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_started = now()
        question = self.llm_service.preprocess_question(query)
        log_event(
            "QCHV",
            "preprocess",
            original_query=query,
            processed_query=question,
        )
        if question != query:
            logger.info("[QCHV] preprocess: %r -> %r", query, question)

        detect_started = now()
        vb_id = self.llm_service.detect_vanban(question)
        vb_display = VANBAN_DISPLAY.get(vb_id, vb_id)
        refs = self._extract_references(question)
        log_event(
            "QCHV",
            "analysis",
            vb_id=vb_id,
            vb_display=vb_display,
            refs=refs,
            retrieval_mode="exact" if refs else "vector",
            elapsed_ms=elapsed_ms(detect_started),
        )

        context = self._collect_context(vb_id, question, refs)
        log_context("QCHV", context)

        generation_started = now()
        answer = self.llm_service.generate_answer(question, context, history, vb_display)
        log_event("QCHV", "generation", elapsed_ms=elapsed_ms(generation_started))
        log_event("QCHV", "done", total_ms=elapsed_ms(total_started))
        return {
            "answer": answer,
            "vb_id": vb_id,
            "vb_display": vb_display,
            "refs": refs,
            "chitchat": False,
            "context": context,
        }


quyche_service = QuyCheService()
