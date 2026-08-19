from __future__ import annotations

"""BƯỚC 05 — XÂY DỰNG CÂY TÀI LIỆU VÀ MỤC

Đầu vào
-------
output/04_document/*_document.json

Đầu ra
------
output/05_hierarchy/*_hierarchy.json

Schema đầu ra
-------------
{
  "metadata": {...},
  "tai_lieu": [
    {
      "id": "doc_1",
      "thu_tu": 1,
      "ten_tai_lieu": "Tên tài liệu đã xác định",
      "muc": [
        {
          "id": "doc_1_muc_1",
          "ky_hieu": "1",
          "noi_dung": [],
          "bang": [],
          "muc_con": []
        }
      ]
    }
  ]
}
"""

import re
from pathlib import Path
from typing import Any

from ..core.hierarchy import DocumentLexer, HierarchyParser, StructureValidator
from ..core.utils.io import load_json_object, save_json


SCRIPT_VERSION = "5.0.0-document-tree"
ROOT_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT_DIR / "output" / "04_document"
OUTPUT_DIR = ROOT_DIR / "output" / "05_hierarchy"
JSON_INDENT = 2


def build_metadata(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "ma_van_ban": document.get("ma_van_ban", ""),
        "ten_file": document.get("ten_file", ""),
        "tieu_de": document.get("tieu_de", ""),
        "ngay_ban_hanh": document.get("ngay_ban_hanh", ""),
    }


def build_hierarchy(document: dict[str, Any]) -> dict[str, Any]:
    events = DocumentLexer(document).run()
    logical_documents = HierarchyParser(events).run()

    raw_result = {
        "metadata": build_metadata(document),
        "tai_lieu": [item.to_dict() for item in logical_documents],
    }
    return StructureValidator().normalize(raw_result)


def output_name(input_path: Path) -> str:
    stem = re.sub(
        r"_document(?:\(\d+\))?$",
        "",
        input_path.stem,
        flags=re.IGNORECASE,
    )
    return f"{stem}_hierarchy.json"


def find_input_files() -> list[Path]:
    if not INPUT_DIR.exists():
        return []
    return sorted(path for path in INPUT_DIR.glob("*.json") if path.is_file())


def count_sections(nodes: list[dict[str, Any]]) -> int:
    total = 0
    for node in nodes:
        total += 1
        children = node.get("muc_con", [])
        if isinstance(children, list):
            total += count_sections(children)
    return total


def count_tables(nodes: list[dict[str, Any]]) -> int:
    total = 0
    for node in nodes:
        tables = node.get("bang", [])
        if isinstance(tables, list):
            total += len(tables)
        children = node.get("muc_con", [])
        if isinstance(children, list):
            total += count_tables(children)
    return total


def process_file(input_path: Path) -> bool:
    try:
        source = load_json_object(input_path)
        result = build_hierarchy(source)
        destination = OUTPUT_DIR / output_name(input_path)
        save_json(result, destination, indent=JSON_INDENT)

        documents = result.get("tai_lieu", [])
        section_count = sum(count_sections(doc.get("muc", [])) for doc in documents)
        table_count = sum(count_tables(doc.get("muc", [])) for doc in documents)

        print(f"[OK] {input_path.name}")
        print(f"     Tài liệu logic: {len(documents)}")
        print(f"     Mục:           {section_count}")
        print(f"     Bảng:          {table_count}")
        print(f"     Đầu ra:        {destination}")
        return True
    except Exception as exc:
        print(f"[LỖI] {input_path.name}: {exc}")
        return False


def main() -> int:
    files = find_input_files()
    if not files:
        print(f"Không tìm thấy JSON trong: {INPUT_DIR}")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    succeeded = sum(process_file(path) for path in files)
    print(f"\nHoàn tất: {succeeded}/{len(files)} file thành công.")
    return 0 if succeeded == len(files) else 1


if __name__ == "__main__":
    raise SystemExit(main())
