from __future__ import annotations

"""Nhập lại toàn bộ tập chunks Thông báo vào Neo4j và ghi báo cáo."""

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings, load_settings
from .importer.thongbao_importer import import_thongbao
from .neo4j_connection import Neo4jConnection


def now_iso() -> str:
    """Trả thời điểm hiện tại theo ISO để dùng thống nhất trong báo cáo."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def find_input_files(input_dir: Path) -> list[Path]:
    """Liệt kê các file chunks đầu vào theo thứ tự ổn định."""
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Không tìm thấy thư mục input: {input_dir}")
    return sorted(
        path for path in input_dir.glob("*_chunks.json") if path.is_file()
    )


def load_json(path: Path) -> dict[str, Any]:
    """Đọc một chunks JSON và kiểm tra object cấp gốc."""
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise TypeError("JSON gốc phải là object.")
    return data


def write_report(report: dict[str, Any], path: Path) -> None:
    """Ghi báo cáo import dưới dạng JSON UTF-8."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)


def build_initial_report(settings: Settings, total_files: int) -> dict[str, Any]:
    """Khởi tạo cấu trúc báo cáo trước khi mở kết nối Neo4j."""
    return {
        "started_at": now_iso(),
        "finished_at": None,
        "database": settings.neo4j_database,
        "input_dir": str(settings.input_dir),
        "total_files": total_files,
        "successful_files": 0,
        "failed_files": 0,
        "deleted_nodes": 0,
        "node_counts": {
            "ThongBao": 0,
            "TaiLieu": 0,
            "Muc": 0,
            "Bang": 0,
            "DongBang": 0,
        },
        "files": [],
    }


def main() -> int:
    """Chạy full import; thao tác này xóa nhánh Thông báo cũ trước khi nhập lại."""
    connection: Neo4jConnection | None = None
    report: dict[str, Any] | None = None
    settings: Settings | None = None

    try:
        settings = load_settings()
        files = find_input_files(settings.input_dir)
        if not files:
            raise FileNotFoundError(
                f"Không có file *_chunks.json trong {settings.input_dir}"
            )

        report = build_initial_report(settings, len(files))
        connection = Neo4jConnection(settings)
        connection.verify()
        print(
            f"[OK] Kết nối Neo4j: {settings.neo4j_uri} "
            f"/ database {settings.neo4j_database}"
        )

        connection.create_constraints()
        print("[OK] Đã kiểm tra 5 unique constraint.")

        deleted_count = connection.delete_thongbao_branch()
        report["deleted_nodes"] = deleted_count
        print(f"[OK] Đã xóa {deleted_count} node thuộc nhánh ThongBao cũ.")

        totals: Counter[str] = Counter()
        for path in files:
            file_result: dict[str, Any] = {
                "file": path.name,
                "status": "failed",
                "node_counts": {},
            }
            try:
                data = load_json(path)
                counts = connection.execute_write(
                    lambda tx, source=data: import_thongbao(tx, source)
                )
                totals.update(counts)
                file_result["status"] = "success"
                file_result["node_counts"] = counts
                report["successful_files"] += 1
                print(f"[OK] {path.name}: {counts}")
            except Exception as error:
                file_result["error"] = str(error)
                report["failed_files"] += 1
                print(f"[LỖI] {path.name}: {error}", file=sys.stderr)
            report["files"].append(file_result)

        report["node_counts"] = {
            label: totals[label]
            for label in ("ThongBao", "TaiLieu", "Muc", "Bang", "DongBang")
        }
        report["finished_at"] = now_iso()
        write_report(report, settings.report_path)

        print(f"Báo cáo: {settings.report_path}")
        print(
            f"Hoàn tất: {report['successful_files']}/{report['total_files']} "
            "file thành công."
        )
        return 0 if report["failed_files"] == 0 else 1

    except Exception as error:
        print(f"[LỖI] {error}", file=sys.stderr)
        if report is not None and settings is not None:
            report["fatal_error"] = str(error)
            report["finished_at"] = now_iso()
            write_report(report, settings.report_path)
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
