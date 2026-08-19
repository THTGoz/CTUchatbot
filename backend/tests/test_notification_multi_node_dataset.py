from __future__ import annotations

import json
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATASET = BACKEND_ROOT / "evaluation" / "notification_multi_node_5.json"
MAIN_DATASET = BACKEND_ROOT / "evaluation" / "notification_qa_30.json"


def test_multi_node_dataset_has_five_valid_all_group_cases() -> None:
    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert len(cases) == 5
    assert len({case["id"] for case in cases}) == 5

    for case in cases:
        assert case["question"].strip()
        assert case["gold_answer"].strip()
        assert case["required_facts"]
        assert len(case["evidence_groups"]) >= 2
        assert len({group["name"] for group in case["evidence_groups"]}) == len(
            case["evidence_groups"]
        )
        for group in case["evidence_groups"]:
            assert group["any_of"]
            assert all(node_id.strip() for node_id in group["any_of"])


def test_multi_node_subset_is_synchronized_with_main_benchmark() -> None:
    standalone = json.loads(DATASET.read_text(encoding="utf-8"))["cases"]
    main = json.loads(MAIN_DATASET.read_text(encoding="utf-8"))
    main_by_id = {case["id"]: case for case in main}

    for case in standalone:
        embedded = main_by_id[case["id"]]
        assert embedded["group"] == "Multi-node"
        for key in ("question", "gold_answer", "required_facts", "evidence_groups"):
            assert embedded[key] == case[key]
