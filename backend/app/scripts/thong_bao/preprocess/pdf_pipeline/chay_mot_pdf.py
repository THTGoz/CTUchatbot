from __future__ import annotations

r"""CLI debug đủ sáu bước cho đúng một PDF.

Chạy từ thư mục ``backend``:
    python -m app.scripts.thong_bao.preprocess.pdf_pipeline.chay_mot_pdf D:\TaiLieu\thong_bao.pdf
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .pipeline import ROOT_DIR, configure_utf8_console, run_single_input


def parse_args() -> argparse.Namespace:
    """Đọc PDF đầu vào và thư mục output tùy chọn."""
    parser = argparse.ArgumentParser(
        description="Chạy pdf_pipeline cho một file PDF, không quét input/."
    )
    parser.add_argument("pdf", type=Path, help="Đường dẫn đến file PDF cần xử lý.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Thư mục kết quả. Mặc định tạo thư mục mới trong output_single/.",
    )
    return parser.parse_args()


def create_output_directory(pdf: Path, output: Path | None) -> Path:
    """Tạo thư mục mới để một lần debug không ghi đè kết quả trước."""
    if output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output = ROOT_DIR / "output_single" / f"{pdf.stem}_{timestamp}"
    else:
        output = output.expanduser().resolve()

    if output.exists():
        raise FileExistsError(
            f"Thư mục kết quả đã tồn tại: {output}\n"
            "Hãy chọn đường dẫn --output mới để tránh ghi đè dữ liệu."
        )
    output.mkdir(parents=True)
    return output


def chay_pipeline(pdf: Path, output: Path) -> Path:
    """Giữ entrypoint tiếng Việt cũ và chuyển việc điều phối về một nơi chung."""
    return run_single_input(pdf, output, from_step=1, to_step=6)


def main() -> int:
    """Xác thực tham số, chạy một PDF và thông báo JSON cuối."""
    configure_utf8_console()
    args = parse_args()
    pdf = args.pdf.expanduser().resolve()

    try:
        if not pdf.is_file():
            raise FileNotFoundError(f"Không tìm thấy file: {pdf}")
        if pdf.suffix.casefold() != ".pdf":
            raise ValueError(f"File đầu vào phải có đuôi .pdf: {pdf}")

        output = create_output_directory(pdf, args.output)
        final_json = chay_pipeline(pdf, output)
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError) as exc:
        print(f"\n[LỖI] {exc}", file=sys.stderr)
        return 1

    print(f"\nHoàn tất. JSON cuối: {final_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
