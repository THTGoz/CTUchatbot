from __future__ import annotations

"""Điều phối sáu bước PDF -> JSON của miền Thông báo.

Module này chỉ quản lý thứ tự chạy và đường dẫn. Thuật toán xử lý dữ liệu vẫn
nằm độc lập trong ``stages/`` để có thể đọc và kiểm thử từng bước.
"""

import importlib
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


ROOT_DIR = Path(__file__).resolve().parent
STAGES_DIR = ROOT_DIR / "stages"
INPUT_DIR = ROOT_DIR / "input"
OUTPUT_DIR = ROOT_DIR / "output"
BACKEND_DIR = ROOT_DIR.parents[4]
PACKAGE_PREFIX = "app.scripts.thong_bao.preprocess.pdf_pipeline.stages"


@dataclass(frozen=True)
class PipelineStep:
    """Mô tả một bước và hàm xử lý mà orchestrator cần gọi."""

    number: int
    module_name: str
    display_name: str
    input_directory: str
    output_directory: str
    processor_name: str

    @property
    def source_path(self) -> Path:
        """Trả về file Python của bước để kiểm tra cấu trúc dự án."""
        return STAGES_DIR / f"{self.module_name}.py"

    @property
    def script_path(self) -> Path:
        """Alias tương thích với code kiểm tra cấu trúc trước khi sắp xếp lại."""
        return self.source_path

    @property
    def import_path(self) -> str:
        """Trả về module path dùng cho import và ``python -m``."""
        return f"{PACKAGE_PREFIX}.{self.module_name}"

    @property
    def output_path(self) -> Path:
        """Trả về thư mục output mặc định của bước."""
        return OUTPUT_DIR / self.output_directory


PIPELINE_STEPS: tuple[PipelineStep, ...] = (
    PipelineStep(1, "extract_raw", "Trích xuất PDF thô", "input", "01_raw_blocks", "process_pdf"),
    PipelineStep(2, "clean_data", "Làm sạch dữ liệu", "01_raw_blocks", "02_clean", "process_file"),
    PipelineStep(3, "extract_metadata", "Trích xuất metadata", "02_clean", "03_metadata", "process_file"),
    PipelineStep(4, "build_document", "Chuẩn hóa tài liệu", "03_metadata", "04_document", "process_file"),
    PipelineStep(5, "build_hierarchy", "Xây dựng hierarchy", "04_document", "05_hierarchy", "process_file"),
    PipelineStep(6, "build_chunks", "Chuẩn hóa output cuối", "05_hierarchy", "06_chunks", "process_file"),
)


def configure_utf8_console() -> None:
    """Cho phép in tiếng Việt ổn định trên Windows và tiến trình con."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def select_steps(from_step: int, to_step: int) -> tuple[PipelineStep, ...]:
    """Chọn một khoảng bước liên tục và kiểm tra thứ tự hợp lệ."""
    if not 1 <= from_step <= 6 or not 1 <= to_step <= 6:
        raise ValueError("Số bước phải nằm trong khoảng từ 1 đến 6.")
    if from_step > to_step:
        raise ValueError("--from-step không được lớn hơn --to-step.")

    return tuple(
        step for step in PIPELINE_STEPS if from_step <= step.number <= to_step
    )


def validate_project(selected_steps: tuple[PipelineStep, ...]) -> None:
    """Kiểm tra source và dữ liệu đầu vào trước khi chạy batch."""
    if not selected_steps:
        raise ValueError("Không có bước pipeline nào được chọn.")

    missing_sources = [
        str(step.source_path) for step in selected_steps if not step.source_path.is_file()
    ]
    if missing_sources:
        details = "\n".join(f"  - {path}" for path in missing_sources)
        raise FileNotFoundError(f"Thiếu các file pipeline:\n{details}")

    first_step = selected_steps[0]
    input_path = (
        INPUT_DIR
        if first_step.number == 1
        else OUTPUT_DIR / first_step.input_directory
    )
    expected_suffix = ".pdf" if first_step.number == 1 else ".json"
    available_inputs = (
        list(input_path.glob(f"*{expected_suffix}")) if input_path.is_dir() else []
    )
    if not available_inputs:
        raise FileNotFoundError(
            f"Không có file {expected_suffix} cho bước {first_step.number:02d} "
            f"trong: {input_path}"
        )


def clean_outputs(selected_steps: tuple[PipelineStep, ...]) -> None:
    """Xóa đúng các thư mục output được người dùng chọn bằng ``--clean``."""
    for step in selected_steps:
        output_path = step.output_path.resolve()
        if output_path.parent != OUTPUT_DIR.resolve():
            raise ValueError(f"Từ chối xóa đường dẫn ngoài output/: {output_path}")
        if output_path.exists():
            shutil.rmtree(output_path)
            print(f"[CLEAN] Đã xóa: {output_path}")


def run_batch_step(step: PipelineStep) -> float:
    """Chạy một bước cho toàn bộ file bằng cùng Python interpreter hiện tại."""
    separator = "=" * 78
    print(f"\n{separator}")
    print(f"BƯỚC {step.number:02d}/06 — {step.display_name}")
    print(f"Module: {step.import_path}")
    print(separator, flush=True)

    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    started_at = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-m", step.import_path],
        cwd=BACKEND_DIR,
        check=False,
        env=environment,
    )
    elapsed = time.perf_counter() - started_at

    if result.returncode != 0:
        raise RuntimeError(
            f"Bước {step.number:02d} thất bại với mã thoát {result.returncode}: "
            f"{step.module_name}"
        )
    print(f"[OK] Bước {step.number:02d} hoàn thành trong {elapsed:.2f} giây.")
    return elapsed


def load_step(step: PipelineStep) -> ModuleType:
    """Nạp module của một bước khi cần, tránh import PyMuPDF ngoài bước 01."""
    return importlib.import_module(step.import_path)


def expected_output(module: ModuleType, step: PipelineStep, input_path: Path) -> Path:
    """Tính đúng file mà bước vừa chạy phải tạo ra."""
    if step.number == 1:
        return Path(module.OUTPUT_DIR) / f"{input_path.stem}_raw.json"

    output_name = getattr(module, "output_name")
    return Path(module.OUTPUT_DIR) / output_name(input_path)


def run_single_input(
    input_path: Path,
    output_root: Path,
    *,
    from_step: int = 1,
    to_step: int = 6,
) -> Path:
    """Chạy một PDF hoặc JSON trung gian qua một khoảng bước liên tục.

    Hàm này được dùng cho chế độ debug một file và kiểm thử golden master.
    Mỗi bước ghi vào thư mục con riêng, không thay đổi output chính của dự án.
    """
    # Hàm có thể được gọi trực tiếp từ test, không nhất thiết đi qua CLI.
    # Vì vậy UTF-8 phải được thiết lập tại chính entrypoint dùng chung này.
    configure_utf8_console()
    selected_steps = select_steps(from_step, to_step)
    input_path = input_path.expanduser().resolve()
    output_root = output_root.expanduser().resolve()

    if not input_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file đầu vào: {input_path}")
    expected_suffix = ".pdf" if from_step == 1 else ".json"
    if input_path.suffix.casefold() != expected_suffix:
        raise ValueError(
            f"Bước {from_step:02d} cần file {expected_suffix}, nhận được: {input_path}"
        )

    output_root.mkdir(parents=True, exist_ok=True)
    current_path = input_path
    for step in selected_steps:
        step_output = output_root / step.output_directory
        step_output.mkdir(parents=True, exist_ok=True)

        module = load_step(step)
        module.OUTPUT_DIR = step_output
        processor = getattr(module, step.processor_name)

        print(f"\n{'=' * 72}\nBƯỚC {step.number}: {step.display_name}\n{'=' * 72}")
        if not processor(current_path):
            raise RuntimeError(f"Bước {step.number:02d} xử lý thất bại.")

        current_path = expected_output(module, step, current_path)
        if not current_path.is_file():
            raise FileNotFoundError(
                f"Bước {step.number:02d} không tạo file dự kiến: {current_path}"
            )

    return current_path
