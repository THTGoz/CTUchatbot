"""Đánh giá end-to-end pipeline Thông báo bằng ground truth JSON tĩnh.

Script gọi trực tiếp ``ThongBaoPipeline`` và ``LLMService`` giống nhánh
THONG_BAO của orchestrator. Nó không gửi HTTP và không đọc/parse log terminal.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = BACKEND_ROOT / "evaluation" / "notification_qa_30.json"
DEFAULT_OUTPUT = BACKEND_ROOT / "evaluation" / "notification_results_evidence.csv"

# Cho phép chạy trực tiếp: python scripts/evaluate_notifications.py
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

CSV_FIELDS = (
    "id",
    "group",
    "question",
    "gold_answer",
    "required_facts",
    "gold_evidence_groups",
    "top_k",
    "topk_ids",
    "direct_hit_at_k",
    "expanded_ids",
    "bundle_ids",
    "final_evidence_hit",
    "recovered_by_expansion",
    "bot_answer",
    "answer_accuracy",
    "pipeline_ms",
    "generation_ms",
    "total_ms",
    "error",
)
GROUP_ORDER = ("Temporal", "Exact/Table", "Semantic", "Multi-node")

CandidateLike = Mapping[str, Any]


@dataclass(frozen=True)
class NotificationRunResult:
    """Object thật thu được khi chạy một case, kèm latency từng tầng lớn."""

    selected_candidates: Sequence[CandidateLike]
    expanded_candidates: Sequence[CandidateLike]
    top_k: int
    context: str
    answer: str
    pipeline_ms: float
    generation_ms: float
    total_ms: float
    runtime_error: str = ""


class NotificationCaseRunner:
    """Adapter dùng đúng retrieval pipeline và answer generator của ``/chat``."""

    def __init__(self, *, top_k: int = 6, max_context_chars: int = 12000) -> None:
        # Import trễ để unit test metric không khởi tạo model/Neo4j/Ollama.
        from app.services.common.llm_service import LLMService
        from app.services.thong_bao.pipeline import ThongBaoPipeline

        self._pipeline = ThongBaoPipeline()
        self._llm = LLMService()
        self._top_k = top_k
        self._max_context_chars = max_context_chars

    async def run(self, question: str) -> NotificationRunResult:
        """Chạy một câu độc lập; không nhận và không giữ conversation history."""
        total_started = time.perf_counter()
        pipeline_started = time.perf_counter()
        pipeline_result = await self._pipeline.run(
            question,
            top_k=self._top_k,
            max_context_chars=self._max_context_chars,
        )
        pipeline_ms = _elapsed_ms(pipeline_started)

        generation_started = time.perf_counter()
        answer = ""
        runtime_error = ""
        try:
            # Đây là cùng lời gọi trong nhánh THONG_BAO của ChatOrchestrator.
            answer = await self._llm.generate(
                pipeline_result.normalized_query,
                pipeline_result.context,
            )
        except Exception as exc:  # vẫn giữ retrieval trace để chấm hai metric đầu
            runtime_error = _runtime_error("GENERATION", exc)
        generation_ms = _elapsed_ms(generation_started)

        return NotificationRunResult(
            selected_candidates=pipeline_result.selected_candidates,
            expanded_candidates=pipeline_result.expanded_candidates,
            top_k=self._top_k,
            context=pipeline_result.context,
            answer=answer,
            pipeline_ms=pipeline_ms,
            generation_ms=generation_ms,
            total_ms=_elapsed_ms(total_started),
            runtime_error=runtime_error,
        )


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _runtime_error(stage: str, exc: BaseException) -> str:
    message = " ".join(str(exc).split())
    return f"RUNTIME_{stage}:{type(exc).__name__}:{message}"[:1000]


def candidate_node_id(candidate: CandidateLike) -> str:
    """Lấy node ID từ Candidate TypedDict thật của backend."""
    return str(candidate.get("node_id") or "").strip()


def score_direct_hit_at_k(
    selected_candidates: Sequence[CandidateLike],
    gold_any_of: Sequence[str],
    k: int,
) -> int:
    """ANY_OF: một gold evidence xuất hiện trực tiếp trong Top-K là đạt."""
    if k <= 0:
        raise ValueError("k phải lớn hơn 0")
    topk_ids = {
        candidate_node_id(candidate)
        for candidate in selected_candidates[:k]
        if candidate_node_id(candidate)
    }
    return int(bool(topk_ids.intersection(gold_any_of)))


def score_final_evidence_hit(
    selected_candidates: Sequence[CandidateLike],
    expanded_candidates: Sequence[CandidateLike],
    gold_any_of: Sequence[str],
) -> int:
    """ANY_OF trên final bundle gồm cả selected lẫn expanded candidates."""
    bundle_ids = {
        candidate_node_id(candidate)
        for candidate in [*selected_candidates, *expanded_candidates]
        if candidate_node_id(candidate)
    }
    return int(bool(bundle_ids.intersection(gold_any_of)))


def score_direct_evidence_groups_at_k(
    selected_candidates: Sequence[CandidateLike],
    evidence_groups: Sequence[Sequence[str]],
    k: int,
) -> int:
    """ALL_GROUPS: Top-K phải chứa ít nhất một node thuộc từng nhóm ANY_OF."""
    if k <= 0:
        raise ValueError("k phải lớn hơn 0")
    topk_ids = {
        candidate_node_id(candidate)
        for candidate in selected_candidates[:k]
        if candidate_node_id(candidate)
    }
    return int(all(topk_ids.intersection(group) for group in evidence_groups))


def score_final_evidence_groups(
    selected_candidates: Sequence[CandidateLike],
    expanded_candidates: Sequence[CandidateLike],
    evidence_groups: Sequence[Sequence[str]],
) -> int:
    """ALL_GROUPS trên final bundle; mỗi nhóm bên trong dùng quy tắc ANY_OF."""
    bundle_ids = {
        candidate_node_id(candidate)
        for candidate in [*selected_candidates, *expanded_candidates]
        if candidate_node_id(candidate)
    }
    return int(all(bundle_ids.intersection(group) for group in evidence_groups))


class EvaluatorInvariantError(RuntimeError):
    """Báo định nghĩa metric bị vi phạm, không phải lỗi pipeline."""


def score_recovered_by_expansion(direct_hit: int, final_hit: int) -> int:
    """Expansion recovery chỉ xảy ra khi retrieval miss nhưng final bundle hit."""
    if direct_hit == 1 and final_hit == 0:
        raise EvaluatorInvariantError(
            "Direct Hit@K = 1 nhưng Final Evidence Hit = 0 là bất khả thi"
        )
    return int(direct_hit == 0 and final_hit == 1)


def classify_error(
    final_evidence_hit: int,
    answer_accuracy: int | None,
    runtime_error: str = "",
) -> str:
    """Suy ra tầng lỗi; không gán lỗi thế hệ khi đáp án chưa được chấm."""
    if runtime_error:
        return runtime_error
    if answer_accuracy is None:
        return "UNGRADED"
    if answer_accuracy == 1:
        return "OK" if final_evidence_hit == 1 else "GOLD_AUDIT"
    return "GENERATION" if final_evidence_hit == 1 else "EVIDENCE_MISS"


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Đọc JSON tĩnh và fail-fast nếu contract ground truth bị sai."""
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset phải là một JSON array không rỗng")

    required_text = ("id", "group", "question", "gold_answer")
    required_lists = ("required_facts",)
    seen: set[str] = set()
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"Case thứ {index} không phải JSON object")
        for key in required_text:
            if not str(case.get(key) or "").strip():
                raise ValueError(f"Case thứ {index} thiếu {key}")
        case_id = str(case["id"])
        if case_id in seen:
            raise ValueError(f"ID bị trùng: {case_id}")
        seen.add(case_id)
        if case["group"] not in GROUP_ORDER:
            raise ValueError(f"{case_id}: group không hợp lệ: {case['group']}")
        for key in required_lists:
            if not isinstance(case.get(key), list) or not case[key]:
                raise ValueError(f"{case_id}: {key} phải là list không rỗng")
        has_single = "gold_evidence_any_of" in case
        has_multi = "evidence_groups" in case
        if has_single == has_multi:
            raise ValueError(
                f"{case_id}: phải có đúng một trong gold_evidence_any_of/evidence_groups"
            )
        if has_single:
            gold_any_of = case["gold_evidence_any_of"]
            if not isinstance(gold_any_of, list) or not gold_any_of or not all(
                isinstance(node_id, str) and node_id.strip()
                for node_id in gold_any_of
            ):
                raise ValueError(
                    f"{case_id}: gold_evidence_any_of chứa ID rỗng/sai kiểu"
                )
            if case["group"] == "Multi-node":
                raise ValueError(f"{case_id}: Multi-node phải dùng evidence_groups")
            continue

        groups = case["evidence_groups"]
        if not isinstance(groups, list) or len(groups) < 2:
            raise ValueError(f"{case_id}: evidence_groups phải có ít nhất hai nhóm")
        if case["group"] != "Multi-node":
            raise ValueError(f"{case_id}: evidence_groups chỉ dùng cho nhóm Multi-node")
        names: set[str] = set()
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError(f"{case_id}: evidence group không phải JSON object")
            name = str(group.get("name") or "").strip()
            any_of = group.get("any_of")
            if not name or name in names:
                raise ValueError(f"{case_id}: tên evidence group rỗng hoặc bị trùng")
            names.add(name)
            if not isinstance(any_of, list) or not any_of or not all(
                isinstance(node_id, str) and node_id.strip() for node_id in any_of
            ):
                raise ValueError(f"{case_id}/{name}: any_of chứa ID rỗng/sai kiểu")
    return cases


def case_evidence_groups(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Chuẩn hóa single-evidence và multi-node về ALL_GROUPS/ANY_OF."""
    if "evidence_groups" in case:
        return [
            {"name": str(group["name"]), "any_of": list(group["any_of"])}
            for group in case["evidence_groups"]
        ]
    return [
        {
            "name": "primary_evidence",
            "any_of": list(case["gold_evidence_any_of"]),
        }
    ]


def _ordered_unique_ids(candidates: Sequence[CandidateLike]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        node_id = candidate_node_id(candidate)
        if node_id and node_id not in seen:
            seen.add(node_id)
            output.append(node_id)
    return output


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def evaluate_case(
    case: Mapping[str, Any],
    runner: NotificationCaseRunner,
) -> dict[str, Any]:
    """Chạy và chấm metric tự động cho đúng một case."""
    run = await runner.run(str(case["question"]))
    selected = list(run.selected_candidates)
    expanded = list(run.expanded_candidates)
    named_groups = case_evidence_groups(case)
    evidence_groups = [group["any_of"] for group in named_groups]
    direct_hit = score_direct_evidence_groups_at_k(
        selected,
        evidence_groups,
        run.top_k,
    )
    final_hit = score_final_evidence_groups(
        selected,
        expanded,
        evidence_groups,
    )
    recovered = score_recovered_by_expansion(direct_hit, final_hit)
    answer_accuracy: int | None = None
    return {
        "id": case["id"],
        "group": case["group"],
        "question": case["question"],
        "gold_answer": case["gold_answer"],
        "required_facts": _json_cell(case["required_facts"]),
        "gold_evidence_groups": _json_cell(named_groups),
        "top_k": run.top_k,
        "topk_ids": _json_cell(_ordered_unique_ids(selected[:run.top_k])),
        "direct_hit_at_k": direct_hit,
        "expanded_ids": _json_cell(_ordered_unique_ids(expanded)),
        "bundle_ids": _json_cell(_ordered_unique_ids([*selected, *expanded])),
        "final_evidence_hit": final_hit,
        "recovered_by_expansion": recovered,
        "bot_answer": run.answer,
        "answer_accuracy": "",
        "pipeline_ms": run.pipeline_ms,
        "generation_ms": run.generation_ms,
        "total_ms": run.total_ms,
        "error": classify_error(
            final_hit,
            answer_accuracy,
            run.runtime_error,
        ),
    }


def save_results(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    """Ghi atomically để crash giữa chừng không làm hỏng checkpoint trước đó."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def load_results(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(CSV_FIELDS).difference(reader.fieldnames or [])
        if missing:
            raise ValueError(
                "CSV dùng schema metric cũ hoặc không hợp lệ; hãy dùng output mới. "
                f"Thiếu cột: {', '.join(sorted(missing))}"
            )
        return list(reader)


def stored_top_k(rows: Sequence[Mapping[str, Any]]) -> int | None:
    """Xác nhận một CSV không trộn kết quả chạy với các giá trị K khác nhau."""
    if not rows:
        return None
    values: set[int] = set()
    for row in rows:
        try:
            value = int(str(row.get("top_k") or ""))
        except ValueError as exc:
            raise ValueError("CSV chứa top_k không hợp lệ") from exc
        if value <= 0:
            raise ValueError("CSV chứa top_k không hợp lệ")
        values.add(value)
    if len(values) != 1:
        raise ValueError("CSV đang trộn nhiều giá trị top_k")
    return next(iter(values))


def _as_binary(value: object) -> int | None:
    text = str(value if value is not None else "").strip()
    if text in {"0", "1"}:
        return int(text)
    return None


def _ordered_rows(
    row_by_id: Mapping[str, Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    known_order = [str(case["id"]) for case in cases]
    rows = [row_by_id[case_id] for case_id in known_order if case_id in row_by_id]
    rows.extend(
        row for case_id, row in row_by_id.items() if case_id not in known_order
    )
    return rows


def prompt_answer_accuracy(row: Mapping[str, Any]) -> int | None:
    """Chấm thủ công required facts; Enter để giữ trạng thái chưa chấm."""
    print("\n" + "=" * 72)
    print(row["id"])
    print("=" * 72)
    print("\nQUESTION:\n" + str(row["question"]))
    print("\nGOLD ANSWER:\n" + str(row["gold_answer"]))
    print("\nREQUIRED FACTS:")
    try:
        facts = json.loads(str(row["required_facts"]))
    except json.JSONDecodeError:
        facts = [str(row["required_facts"])]
    for fact in facts:
        print(f"- {fact}")
    print("\nBOT ANSWER:\n" + str(row["bot_answer"]))
    while True:
        value = input("\nAnswer Accuracy [0/1, Enter=bỏ qua]: ").strip()
        if not value:
            return None
        if value in {"0", "1"}:
            return int(value)
        print("Chỉ nhập 0, 1 hoặc Enter.")


def apply_manual_grade(row: dict[str, Any], grade: int | None) -> None:
    if grade is None:
        return
    row["answer_accuracy"] = grade
    row["error"] = classify_error(
        _as_binary(row.get("final_evidence_hit")) or 0,
        grade,
        str(row.get("error") or "")
        if str(row.get("error") or "").startswith("RUNTIME_")
        else "",
    )


def _metric(values: Sequence[int]) -> str:
    if not values:
        return "N/A (0/0)"
    return f"{sum(values) / len(values) * 100:.1f}% ({sum(values)}/{len(values)})"


def _expansion_recovery_metric(rows: Sequence[Mapping[str, Any]]) -> str:
    direct_misses = [
        row
        for row in rows
        if _as_binary(row.get("direct_hit_at_k")) == 0
    ]
    if not direct_misses:
        return "N/A (0/0)"
    recovered = sum(
        _as_binary(row.get("recovered_by_expansion")) or 0
        for row in direct_misses
    )
    return f"{recovered}/{len(direct_misses)} = {recovered / len(direct_misses) * 100:.1f}%"


def print_summary(rows: Sequence[Mapping[str, Any]], top_k: int) -> None:
    """In macro view theo các nhóm và Overall; Accuracy bỏ qua case chưa chấm."""
    print("\nSUMMARY")
    print(
        f"{'Group':<14} {f'Direct Hit@{top_k}':>20} "
        f"{'Final Evidence Hit':>22} {'Answer Accuracy':>20}"
    )
    print("-" * 80)
    for group in (*GROUP_ORDER, "Overall"):
        subset = list(rows) if group == "Overall" else [
            row for row in rows if row.get("group") == group
        ]
        direct = [
            value
            for row in subset
            if (value := _as_binary(row.get("direct_hit_at_k"))) is not None
        ]
        final = [
            value
            for row in subset
            if (value := _as_binary(row.get("final_evidence_hit"))) is not None
        ]
        accuracy = [
            value
            for row in subset
            if (value := _as_binary(row.get("answer_accuracy"))) is not None
        ]
        print(
            f"{group:<14} {_metric(direct):>20} "
            f"{_metric(final):>22} {_metric(accuracy):>20}"
        )

    print("\nExpansion Recovery Rate")
    for group in (*GROUP_ORDER, "Overall"):
        subset = list(rows) if group == "Overall" else [
            row for row in rows if row.get("group") == group
        ]
        print(f"{group:<14} {_expansion_recovery_metric(subset)}")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("giá trị phải lớn hơn 0")
    return parsed


def _env_positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _configure_utf8_console() -> None:
    """Tránh lỗi UnicodeEncodeError trên Windows console dùng code page CP1252."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Chỉ chạy ID này; có thể truyền nhiều lần.",
    )
    parser.add_argument("--limit", type=_positive_int)
    parser.add_argument(
        "--top-k",
        type=_positive_int,
        default=_env_positive_int("CHAT_GLOBAL_TOP_K", 6),
    )
    parser.add_argument(
        "--max-context-chars",
        type=_positive_int,
        default=_env_positive_int("MAX_CONTEXT_CHARS", 12000),
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Bỏ qua ID đã có trong CSV (mặc định: true).",
    )
    parser.add_argument(
        "--grade-answers",
        action="store_true",
        help="Hỏi 0/1 sau từng answer; Enter để chấm sau.",
    )
    parser.add_argument(
        "--grade-only",
        action="store_true",
        help="Chỉ chấm các answer đã có trong CSV, không gọi pipeline.",
    )
    parser.add_argument(
        "--regrade",
        action="store_true",
        help="Với --grade-only, hỏi lại cả những case đã chấm.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Dừng ngay khi một case gặp runtime error.",
    )
    return parser.parse_args(argv)


def _select_cases(
    all_cases: Sequence[dict[str, Any]],
    case_ids: Sequence[str] | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    selected = list(all_cases)
    if case_ids:
        requested = set(case_ids)
        known = {str(case["id"]) for case in all_cases}
        unknown = sorted(requested - known)
        if unknown:
            raise ValueError("ID không có trong dataset: " + ", ".join(unknown))
        selected = [case for case in selected if case["id"] in requested]
    return selected[:limit] if limit else selected


def _grade_existing(
    selected_cases: Sequence[Mapping[str, Any]],
    all_cases: Sequence[Mapping[str, Any]],
    row_by_id: dict[str, dict[str, Any]],
    output: Path,
    *,
    regrade: bool,
) -> None:
    for case in selected_cases:
        case_id = str(case["id"])
        row = row_by_id.get(case_id)
        if row is None:
            print(f"[{case_id}] chưa có kết quả, bỏ qua.")
            continue
        if _as_binary(row.get("answer_accuracy")) is not None and not regrade:
            continue
        grade = prompt_answer_accuracy(row)
        apply_manual_grade(row, grade)
        save_results(_ordered_rows(row_by_id, all_cases), output)


async def async_main(args: argparse.Namespace) -> int:
    all_cases = load_cases(args.dataset.resolve())
    selected_cases = _select_cases(all_cases, args.case_ids, args.limit)
    existing_rows = load_results(args.output.resolve())
    existing_top_k = stored_top_k(existing_rows)
    row_by_id: dict[str, dict[str, Any]] = {
        str(row.get("id")): row for row in existing_rows if row.get("id")
    }

    if args.grade_only:
        if not existing_rows:
            raise FileNotFoundError(f"Chưa có CSV để chấm: {args.output.resolve()}")
        _grade_existing(
            selected_cases,
            all_cases,
            row_by_id,
            args.output.resolve(),
            regrade=args.regrade,
        )
        print_summary(_ordered_rows(row_by_id, all_cases), existing_top_k or args.top_k)
        return 0

    if existing_top_k is not None and existing_top_k != args.top_k:
        raise ValueError(
            f"CSV hiện có dùng top_k={existing_top_k}, nhưng lần chạy này dùng "
            f"top_k={args.top_k}; hãy chọn output mới hoặc dùng cùng K"
        )

    pending = [
        case
        for case in selected_cases
        if not args.resume or str(case["id"]) not in row_by_id
    ]
    if not pending:
        print("Không có case cần chạy; dùng --no-resume để chạy lại.")
        print_summary(_ordered_rows(row_by_id, all_cases), args.top_k)
        return 0

    runner = NotificationCaseRunner(
        top_k=args.top_k,
        max_context_chars=args.max_context_chars,
    )
    try:
        for index, case in enumerate(pending, start=1):
            case_id = str(case["id"])
            print(f"[{index}/{len(pending)}] {case_id}")
            started = time.perf_counter()
            try:
                row = await evaluate_case(case, runner)
            except EvaluatorInvariantError:
                raise
            except Exception as exc:
                row = {
                    "id": case_id,
                    "group": case["group"],
                    "question": case["question"],
                    "gold_answer": case["gold_answer"],
                    "required_facts": _json_cell(case["required_facts"]),
                    "top_k": args.top_k,
                    "topk_ids": "[]",
                    "direct_hit_at_k": "",
                    "expanded_ids": "[]",
                    "bundle_ids": "[]",
                    "final_evidence_hit": "",
                    "recovered_by_expansion": "",
                    "bot_answer": "",
                    "answer_accuracy": "",
                    "pipeline_ms": "",
                    "generation_ms": "",
                    "total_ms": _elapsed_ms(started),
                    "error": _runtime_error("PIPELINE", exc),
                }
            row_by_id[case_id] = row

            # Checkpoint trước prompt để Ctrl+C lúc chấm không làm mất case vừa chạy.
            save_results(_ordered_rows(row_by_id, all_cases), args.output.resolve())
            print(
                f"  hit@{args.top_k}={row['direct_hit_at_k']} "
                f"final={row['final_evidence_hit']} "
                f"recovered={row['recovered_by_expansion']} "
                f"total_ms={row['total_ms']} error={row['error']}"
            )
            if args.grade_answers and row.get("bot_answer"):
                grade = prompt_answer_accuracy(row)
                apply_manual_grade(row, grade)
                save_results(_ordered_rows(row_by_id, all_cases), args.output.resolve())
            if args.fail_fast and str(row.get("error") or "").startswith("RUNTIME_"):
                break
    except KeyboardInterrupt:
        print("\nĐã dừng theo yêu cầu; checkpoint CSV gần nhất đã được lưu.")

    final_rows = _ordered_rows(row_by_id, all_cases)
    print_summary(final_rows, args.top_k)
    print(f"\nCSV: {args.output.resolve()}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_console()
    args = parse_args(argv)
    try:
        return asyncio.run(async_main(args))
    except (FileNotFoundError, ValueError, EvaluatorInvariantError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
