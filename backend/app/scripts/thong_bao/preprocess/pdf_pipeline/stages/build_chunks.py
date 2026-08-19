from __future__ import annotations

"""BƯỚC 06 — CHUẨN HÓA VÀ XÁC THỰC JSON CUỐI

Bước 05 đã xây xong cấu trúc ``metadata -> tai_lieu -> muc -> muc_con``.
Bước 06 không suy luận lại hierarchy; chỉ chuẩn hóa kiểu dữ liệu, loại chuỗi
rỗng và ghi JSON cuối vào output/06_chunks/.
"""

import re
from pathlib import Path
from typing import Any

from ..core.hierarchy import StructureValidator
from ..core.utils.io import load_json_object, save_json


SCRIPT_VERSION = "2.0.0-finalize"
ROOT_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT_DIR / "output" / "05_hierarchy"
OUTPUT_DIR = ROOT_DIR / "output" / "06_chunks"
JSON_INDENT = 2


def finalize_document(document: dict[str, Any]) -> dict[str, Any]:
    return StructureValidator().normalize(document)


def output_name(input_path: Path) -> str:
    stem = re.sub(
        r"_hierarchy(?:\(\d+\))?$",
        "",
        input_path.stem,
        flags=re.IGNORECASE,
    )
    return f"{stem}_chunks.json"


def find_input_files() -> list[Path]:
    if not INPUT_DIR.exists():
        return []
    return sorted(path for path in INPUT_DIR.glob("*.json") if path.is_file())


def process_file(input_path: Path) -> bool:
    try:
        source = load_json_object(input_path)
        result = finalize_document(source)
        destination = OUTPUT_DIR / output_name(input_path)
        save_json(result, destination, indent=JSON_INDENT)
        print(f"[OK] {input_path.name} -> {destination.name}")
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
