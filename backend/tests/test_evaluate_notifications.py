from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.evaluate_notifications import (  # noqa: E402
    EvaluatorInvariantError,
    NotificationRunResult,
    classify_error,
    evaluate_case,
    load_cases,
    load_results,
    print_summary,
    save_results,
    score_direct_hit_at_k,
    score_direct_evidence_groups_at_k,
    score_final_evidence_hit,
    score_final_evidence_groups,
    score_recovered_by_expansion,
    stored_top_k,
)


def candidate(node_id: str) -> dict[str, str]:
    return {"node_id": node_id}


def test_case_a_gold_at_rank_one_is_direct_and_final_not_recovered() -> None:
    selected = [candidate("GOLD"), candidate("other")]
    direct = score_direct_hit_at_k(selected, ["GOLD"], 6)
    final = score_final_evidence_hit(selected, [], ["GOLD"])
    assert (direct, final, score_recovered_by_expansion(direct, final)) == (1, 1, 0)


def test_case_b_gold_at_rank_k_is_still_direct_not_recovered() -> None:
    selected = [candidate(value) for value in ["A", "B", "C", "D", "E", "GOLD"]]
    direct = score_direct_hit_at_k(selected, ["GOLD"], 6)
    final = score_final_evidence_hit(selected, [], ["GOLD"])
    assert (direct, final, score_recovered_by_expansion(direct, final)) == (1, 1, 0)
    assert score_direct_hit_at_k(selected, ["GOLD"], 5) == 0


def test_case_c_expansion_recovers_direct_miss() -> None:
    selected = [candidate("anchor")]
    expanded = [candidate("GOLD")]
    direct = score_direct_hit_at_k(selected, ["GOLD"], 6)
    final = score_final_evidence_hit(selected, expanded, ["GOLD"])
    assert (direct, final, score_recovered_by_expansion(direct, final)) == (0, 1, 1)


def test_case_d_gold_missing_from_final_bundle_is_not_recovered() -> None:
    selected = [candidate("anchor")]
    expanded = [candidate("related")]
    direct = score_direct_hit_at_k(selected, ["GOLD"], 6)
    final = score_final_evidence_hit(selected, expanded, ["GOLD"])
    assert (direct, final, score_recovered_by_expansion(direct, final)) == (0, 0, 0)


def test_case_e_direct_hit_without_final_hit_raises_invariant_error() -> None:
    with pytest.raises(EvaluatorInvariantError):
        score_recovered_by_expansion(1, 0)


def test_all_groups_require_one_node_from_every_group() -> None:
    groups = [["A", "A_EQUIVALENT"], ["B"]]
    selected = [candidate("A")]
    expanded = [candidate("B")]
    assert score_direct_evidence_groups_at_k(selected, groups, 6) == 0
    assert score_final_evidence_groups(selected, expanded, groups) == 1


def test_all_groups_do_not_treat_different_groups_as_any_of() -> None:
    groups = [["A"], ["B"]]
    selected = [candidate("A")]
    assert score_direct_evidence_groups_at_k(selected, groups, 6) == 0
    assert score_final_evidence_groups(selected, [], groups) == 0


def test_error_classification_uses_final_evidence_and_answer_accuracy() -> None:
    assert classify_error(1, None) == "UNGRADED"
    assert classify_error(1, 1) == "OK"
    assert classify_error(0, 1) == "GOLD_AUDIT"
    assert classify_error(0, 0) == "EVIDENCE_MISS"
    assert classify_error(1, 0) == "GENERATION"


def test_static_dataset_has_30_single_and_5_multi_node_cases() -> None:
    cases = load_cases(BACKEND_ROOT / "evaluation" / "notification_qa_30.json")
    assert len(cases) == 35
    assert len({case["id"] for case in cases}) == 35
    assert [case["group"] for case in cases].count("Temporal") == 10
    assert [case["group"] for case in cases].count("Exact/Table") == 10
    assert [case["group"] for case in cases].count("Semantic") == 10
    assert [case["group"] for case in cases].count("Multi-node") == 5
    single_cases = [case for case in cases if case["group"] != "Multi-node"]
    multi_cases = [case for case in cases if case["group"] == "Multi-node"]
    assert all(case["gold_evidence_any_of"] for case in single_cases)
    assert all("direct_seed_any_of" not in case for case in cases)
    assert all("evidence_groups" not in case for case in single_cases)
    assert all(len(case["evidence_groups"]) >= 2 for case in multi_cases)
    assert all("gold_evidence_any_of" not in case for case in multi_cases)

    by_id = {case["id"]: case for case in cases}
    assert by_id["T07"]["gold_evidence_any_of"] == ["Tet2026_doc_1_muc_1"]
    assert by_id["T07"]["required_facts"] == [
        "holiday_start=2026-02-09",
        "holiday_end=2026-02-22",
    ]
    assert by_id["S05"]["gold_evidence_any_of"] == [
        "KHGDVDKHP_HK1_26_27_doc_2_muc_5"
    ]


def result_row() -> dict[str, object]:
    return {
        "id": "T01",
        "group": "Temporal",
        "question": "Kế hoạch bắt đầu khi nào?",
        "gold_answer": "Ngày 07/09/2026.",
        "required_facts": '["training_start=2026-09-07"]',
        "gold_evidence_groups": '[{"name":"primary_evidence","any_of":["gold"]}]',
        "top_k": 6,
        "topk_ids": '["gold"]',
        "direct_hit_at_k": 1,
        "expanded_ids": "[]",
        "bundle_ids": '["gold"]',
        "final_evidence_hit": 1,
        "recovered_by_expansion": 0,
        "bot_answer": "Bắt đầu ngày 07/09/2026.",
        "answer_accuracy": "",
        "pipeline_ms": 10.0,
        "generation_ms": 20.0,
        "total_ms": 30.0,
        "error": "UNGRADED",
    }


def test_csv_checkpoint_round_trip_preserves_unicode_and_top_k(tmp_path: Path) -> None:
    path = tmp_path / "results.csv"
    row = result_row()
    save_results([row], path)
    loaded = load_results(path)
    assert loaded[0]["question"] == row["question"]
    assert loaded[0]["bot_answer"] == row["bot_answer"]
    assert stored_top_k(loaded) == 6
    assert not path.with_suffix(".csv.tmp").exists()


def test_old_csv_schema_is_rejected_instead_of_silently_migrated(tmp_path: Path) -> None:
    path = tmp_path / "old-results.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "top5_ids", "direct_hit_at_5"])
        writer.writeheader()
        writer.writerow({"id": "T01", "top5_ids": "[]", "direct_hit_at_5": 0})
    with pytest.raises(ValueError, match="schema metric cũ"):
        load_results(path)


def test_summary_reports_configured_k_and_expansion_recovery_rate(capsys: pytest.CaptureFixture[str]) -> None:
    rows = [
        {
            "group": "Temporal",
            "direct_hit_at_k": 1,
            "final_evidence_hit": 1,
            "recovered_by_expansion": 0,
            "answer_accuracy": 1,
        },
        {
            "group": "Temporal",
            "direct_hit_at_k": 0,
            "final_evidence_hit": 1,
            "recovered_by_expansion": 1,
            "answer_accuracy": 1,
        },
        {
            "group": "Temporal",
            "direct_hit_at_k": 0,
            "final_evidence_hit": 0,
            "recovered_by_expansion": 0,
            "answer_accuracy": 0,
        },
    ]
    print_summary(rows, 6)
    output = capsys.readouterr().out
    assert "Direct Hit@6" in output
    assert "Final Evidence Hit" in output
    assert "Overall        1/2 = 50.0%" in output


def test_evaluate_case_uses_same_top_k_as_pipeline_run() -> None:
    class FakeRunner:
        async def run(self, question: str) -> NotificationRunResult:
            assert question == "Câu hỏi"
            return NotificationRunResult(
                selected_candidates=[
                    candidate("A"),
                    candidate("B"),
                    candidate("C"),
                    candidate("D"),
                    candidate("E"),
                    candidate("GOLD"),
                ],
                expanded_candidates=[],
                top_k=6,
                context="context thật",
                answer="câu trả lời",
                pipeline_ms=11.0,
                generation_ms=22.0,
                total_ms=33.0,
            )

    case = {
        "id": "X01",
        "group": "Temporal",
        "question": "Câu hỏi",
        "gold_answer": "Đáp án",
        "required_facts": ["fact=1"],
        "gold_evidence_any_of": ["GOLD"],
    }
    row = asyncio.run(evaluate_case(case, FakeRunner()))  # type: ignore[arg-type]
    assert row["top_k"] == 6
    assert row["direct_hit_at_k"] == 1
    assert row["final_evidence_hit"] == 1
    assert row["recovered_by_expansion"] == 0
    assert row["error"] == "UNGRADED"
    assert row["total_ms"] == 33.0


def test_evaluate_multi_node_case_requires_all_groups() -> None:
    class FakeRunner:
        async def run(self, question: str) -> NotificationRunResult:
            return NotificationRunResult(
                selected_candidates=[candidate("A")],
                expanded_candidates=[candidate("B")],
                top_k=6,
                context="context thật",
                answer="câu trả lời",
                pipeline_ms=11.0,
                generation_ms=22.0,
                total_ms=33.0,
            )

    case = {
        "id": "MNXX",
        "group": "Multi-node",
        "question": "Câu hỏi nhiều node",
        "gold_answer": "Đáp án",
        "required_facts": ["fact_a=1", "fact_b=1"],
        "evidence_groups": [
            {"name": "first", "any_of": ["A"]},
            {"name": "second", "any_of": ["B"]},
        ],
    }
    row = asyncio.run(evaluate_case(case, FakeRunner()))  # type: ignore[arg-type]
    assert row["direct_hit_at_k"] == 0
    assert row["final_evidence_hit"] == 1
    assert row["recovered_by_expansion"] == 1
