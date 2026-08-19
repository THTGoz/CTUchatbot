from __future__ import annotations

"""CLI chạy batch toàn bộ pipeline PDF -> JSON Thông báo.

Chạy từ thư mục ``backend``:
    python -m app.scripts.thong_bao.preprocess.pdf_pipeline.main
    python -m app.scripts.thong_bao.preprocess.pdf_pipeline.main --from-step 2
"""

import argparse
import sys
import time

from pipeline import (
    OUTPUT_DIR,
    PIPELINE_STEPS,
    ROOT_DIR,
    clean_outputs,
    configure_utf8_console,
    run_batch_step,
    select_steps,
    validate_project,
)


def parse_args() -> argparse.Namespace:
    """Đọc phạm vi các bước và tùy chọn dọn output từ command line."""
    parser = argparse.ArgumentParser(
        description="Chạy pipeline PDF-to-JSON Thông báo theo thứ tự 01 đến 06."
    )
    parser.add_argument(
        "--from-step",
        type=int,
        choices=range(1, 7),
        default=1,
        metavar="N",
        help="Bước bắt đầu, từ 1 đến 6. Mặc định: 1.",
    )
    parser.add_argument(
        "--to-step",
        type=int,
        choices=range(1, 7),
        default=6,
        metavar="N",
        help="Bước kết thúc, từ 1 đến 6. Mặc định: 6.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Xóa output của các bước được chọn trước khi chạy.",
    )
    return parser.parse_args()


def main() -> int:
    """Chạy các bước đã chọn và in báo cáo thời gian."""
    configure_utf8_console()
    args = parse_args()

    try:
        selected_steps = select_steps(args.from_step, args.to_step)
        validate_project(selected_steps)

        print("Notification PDF-to-JSON Pipeline")
        print(f"Project : {ROOT_DIR}")
        print(f"Python  : {sys.executable}")
        print(f"Phạm vi : bước {args.from_step:02d} -> {args.to_step:02d}")

        if args.clean:
            clean_outputs(selected_steps)

        started_at = time.perf_counter()
        timings = [(step, run_batch_step(step)) for step in selected_steps]
        total_elapsed = time.perf_counter() - started_at

        print("\n" + "=" * 78)
        print("PIPELINE HOÀN THÀNH")
        print("=" * 78)
        for step, elapsed in timings:
            print(f"  Bước {step.number:02d}: {step.display_name:<28} {elapsed:>8.2f} giây")
        print(f"  Tổng thời gian: {total_elapsed:.2f} giây")
        print(f"  Output cuối  : {OUTPUT_DIR / '06_chunks'}")
        return 0
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"\n[LỖI] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[ĐÃ DỪNG] Người dùng đã hủy pipeline.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
