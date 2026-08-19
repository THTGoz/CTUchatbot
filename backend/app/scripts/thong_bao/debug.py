"""Script debug pipeline THONG_BAO, không chạy router, CTDT hoặc QCHV."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from app.services.common.candidate import Candidate
from app.services.thong_bao.pipeline import ThongBaoPipeline, ThongBaoPipelineResult
from app.services.thong_bao.retriever import doc_gia_tri_exact_co_ban


def _configure_utf8_console() -> None:
    """Buộc stdout/stderr dùng UTF-8 để PowerShell cũ in được tiếng Việt."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def _load_project_environment() -> None:
    """Nạp `.env` ở backend hoặc project root trước khi kết nối model và Neo4j."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        # Cho phép xem `--help` ngay cả khi môi trường phát triển chưa cài requirements.
        return

    backend_root = Path(__file__).resolve().parents[3]
    project_root = backend_root.parent
    load_dotenv(backend_root / ".env", override=False)
    load_dotenv(project_root / ".env", override=False)


def _build_argument_parser() -> argparse.ArgumentParser:
    """Tạo command-line interface với chế độ một câu hoặc nhập tương tác."""
    parser = argparse.ArgumentParser(
        description=(
            "Debug riêng THONG_BAO: normalize → embedding → temporal/exact "
            "→ chọn exact hoặc vector → expansion → context."
        ),
    )
    parser.add_argument("query", nargs="?", help="Câu hỏi Thông báo cần kiểm tra.")
    parser.add_argument("--top-k", type=int, default=6, help="Số candidate gốc tối đa (mặc định: 6).")
    parser.add_argument(
        "--max-context-chars",
        type=int,
        default=12000,
        help="Giới hạn ký tự của context cuối (mặc định: 12000).",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Nhập nhiều câu liên tiếp; dùng 'exit' để kết thúc.",
    )
    parser.add_argument("--json", action="store_true", help="In toàn bộ kết quả dưới dạng JSON.")
    parser.add_argument("--verbose", action="store_true", help="Bật log DEBUG của pipeline.")
    return parser


def _candidate_to_dict(candidate: Candidate) -> dict[str, object]:
    """Chuyển Candidate sang dict có thứ tự trường thuận tiện khi đọc debug."""
    return {
        "node_id": candidate["node_id"],
        "label": candidate["label"],
        "source": candidate["source"],
        "cosine_score": candidate["cosine_score"],
        "properties": candidate["properties"],
        "metadata": candidate["metadata"],
    }


def _detected_exact_values(
    normalized_query: str,
    result: ThongBaoPipelineResult,
) -> dict[str, str]:
    """Gom exact cơ bản và tên ngành mà retriever đã phát hiện từ Neo4j."""
    exact = {
        str(key): str(value)
        for key, value in result.exact_values.items()
        if str(value).strip()
    }
    if not exact:
        exact = doc_gia_tri_exact_co_ban(normalized_query)
    for candidate in result.candidates:
        candidate_exact = candidate["metadata"].get("exact_columns") or {}
        if isinstance(candidate_exact, dict):
            exact.update(
                {
                    str(key): str(value)
                    for key, value in candidate_exact.items()
                    if str(value).strip()
                }
            )
    return exact


def _expansion_by_seed(result: ThongBaoPipelineResult) -> dict[str, list[dict[str, object]]]:
    """Nhóm evidence theo anchor để debug không làm phẳng các seed bundle."""
    grouped = {seed["node_id"]: [] for seed in result.selected_candidates}
    for candidate in result.expanded_candidates:
        anchor = str(candidate["metadata"].get("anchor_node_id") or "")
        if anchor in grouped:
            grouped[anchor].append(_candidate_to_dict(candidate))
    return grouped


def _print_candidate_group(title: str, candidates: list[Candidate]) -> None:
    """In một tầng candidate đủ ngắn để so exact/vector/grouping bằng mắt."""
    print(f"{title}: {len(candidates)}")
    for position, candidate in enumerate(candidates, start=1):
        table_id = candidate["metadata"].get("parent_table_id") or "-"
        print(
            f"  [{position}] {candidate['label']} | "
            f"source={candidate['source']} | "
            f"score={candidate['cosine_score']:.4f} | "
            f"table={table_id} | id={candidate['node_id']}"
        )


def _result_to_dict(query: str, result: ThongBaoPipelineResult) -> dict[str, object]:
    """Gom trace của tất cả tầng pipeline thành một payload JSON duy nhất."""
    original_query = result.original_query or query
    normalized_query = result.normalized_query or original_query
    return {
        "original_query": original_query,
        "normalized_query": normalized_query,
        "domain": "THONG_BAO",
        "detected_exact_values": _detected_exact_values(normalized_query, result),
        "temporal": asdict(result.temporal_scope),
        "allowed_notification_ids": result.notification_ids,
        "asks_list": result.asks_list,
        "embedding_query": normalized_query,
        "embedding_dimensions": len(result.vector),
        "candidate_count": len(result.candidates),
        "selected_count": len(result.selected_candidates),
        "expanded_count": len(result.expanded_candidates),
        "exact_candidates_before_grouping": [
            _candidate_to_dict(item) for item in result.exact_candidates
        ],
        "exact_candidates_after_grouping": [
            _candidate_to_dict(item) for item in result.grouped_exact_candidates
        ],
        "vector_candidates": [
            _candidate_to_dict(item) for item in result.vector_candidates
        ],
        "retrieval_candidates": [_candidate_to_dict(item) for item in result.candidates],
        "selected_seeds": [
            _candidate_to_dict(item) for item in result.selected_candidates
        ],
        "expansion_by_seed": _expansion_by_seed(result),
        "context": result.context,
    }


def _print_human_readable(query: str, result: ThongBaoPipelineResult) -> None:
    """In trace ngắn gọn theo từng bước để đọc trực tiếp trong terminal."""
    original_query = result.original_query or query
    normalized_query = result.normalized_query or original_query
    temporal = asdict(result.temporal_scope)
    exact_values = _detected_exact_values(normalized_query, result)
    print(f"\nOriginal query: {original_query}")
    print(f"Normalized query: {normalized_query}")
    print("Domain: THONG_BAO")
    print(f"Detected exact values: {json.dumps(exact_values, ensure_ascii=False)}")
    print(f"Temporal/filter: {json.dumps(temporal, ensure_ascii=False)}")
    print(f"Allowed notification IDs: {json.dumps(result.notification_ids, ensure_ascii=False)}")
    print(f"asks_list: {str(result.asks_list).lower()}")
    print(f"Query dùng để embedding: {normalized_query}")
    print(f"Embedding dimensions: {len(result.vector)}")
    print(
        "Candidates: "
        f"raw={len(result.candidates)}, "
        f"selected={len(result.selected_candidates)}, "
        f"expanded={len(result.expanded_candidates)}"
    )

    _print_candidate_group("Exact trước grouping", result.exact_candidates)
    _print_candidate_group("Exact sau grouping", result.grouped_exact_candidates)
    _print_candidate_group("Vector candidates", result.vector_candidates)
    _print_candidate_group("Retrieval candidates", result.candidates)
    _print_candidate_group("Selected seeds", result.selected_candidates)

    print("Expansion theo seed:")
    for seed_id, evidence in _expansion_by_seed(result).items():
        print(f"  {seed_id}: {len(evidence)} evidence")

    print("\nContext cuối:")
    print(result.context)


async def _debug_one_query(
    pipeline: ThongBaoPipeline,
    query: str,
    *,
    top_k: int,
    max_context_chars: int,
    output_json: bool,
) -> None:
    """Chạy và in kết quả debug cho đúng một câu hỏi."""
    result = await pipeline.run(
        query,
        top_k=top_k,
        max_context_chars=max_context_chars,
    )
    if output_json:
        payload = _result_to_dict(query, result)
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return
    _print_human_readable(query, result)


async def _run_interactive(
    pipeline: ThongBaoPipeline,
    *,
    top_k: int,
    max_context_chars: int,
    output_json: bool,
) -> None:
    """Giữ model/driver sống để debug nhiều câu mà không phải khởi động lại."""
    print("Debug THONG_BAO tương tác. Nhập 'exit' hoặc 'quit' để kết thúc.")
    while True:
        query = input("\nTHONG_BAO> ").strip()
        if query.casefold() in {"exit", "quit"}:
            return
        if not query:
            continue
        await _debug_one_query(
            pipeline,
            query,
            top_k=top_k,
            max_context_chars=max_context_chars,
            output_json=output_json,
        )


def _close_shared_driver() -> None:
    """Đóng Neo4j driver sau phiên debug để tiến trình thoát sạch."""
    try:
        from app.db.neo4j import close_driver

        close_driver()
    except ImportError:
        return


def main(argv: Sequence[str] | None = None) -> int:
    """Entrypoint CLI; trả mã lỗi khác 0 khi pipeline không chạy được."""
    _configure_utf8_console()
    parser = _build_argument_parser()
    args = parser.parse_args(argv)
    if not args.interactive and not (args.query or "").strip():
        parser.error("Cần truyền query hoặc dùng --interactive")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    _load_project_environment()
    pipeline = ThongBaoPipeline()

    try:
        if args.interactive:
            asyncio.run(
                _run_interactive(
                    pipeline,
                    top_k=args.top_k,
                    max_context_chars=args.max_context_chars,
                    output_json=args.json,
                )
            )
        else:
            asyncio.run(
                _debug_one_query(
                    pipeline,
                    args.query.strip(),
                    top_k=args.top_k,
                    max_context_chars=args.max_context_chars,
                    output_json=args.json,
                )
            )
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logging.getLogger("app.thong_bao.debug").exception("Pipeline debug thất bại")
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 1
    finally:
        _close_shared_driver()


if __name__ == "__main__":
    raise SystemExit(main())
