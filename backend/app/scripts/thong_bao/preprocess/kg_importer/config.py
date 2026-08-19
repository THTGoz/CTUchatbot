from __future__ import annotations

"""Cấu hình dùng chung cho importer và embedding Thông báo."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parent
PREPROCESS_DIR = PROJECT_DIR.parent
BACKEND_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_INPUT_DIR = (
    PREPROCESS_DIR / "pdf_pipeline" / "output" / "06_chunks"
)


@dataclass(frozen=True)
class Settings:
    """Các tham số kết nối, input và embedding sau khi đọc từ environment."""

    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    neo4j_database: str
    input_dir: Path
    report_path: Path
    embedding_model_name: str
    embedding_device: str
    embedding_dimension: int
    embedding_batch_size: int


def load_settings() -> Settings:
    """Đọc cấu hình từ `backend/.env` và áp dụng default an toàn."""
    # Backend và importer dùng chung một file .env để tránh lệch database/model.
    load_dotenv(BACKEND_ROOT / ".env")

    password = os.getenv("NEO4J_PASSWORD", "").strip()
    if not password:
        raise ValueError(
            "Thiếu NEO4J_PASSWORD. Hãy tạo backend/.env và điền mật khẩu Neo4j."
        )

    input_dir = Path(
        os.getenv("INPUT_DIR", str(DEFAULT_INPUT_DIR))
    ).expanduser().resolve()

    return Settings(
        neo4j_uri=os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687").strip(),
        neo4j_username=os.getenv("NEO4J_USERNAME", "neo4j").strip(),
        neo4j_password=password,
        neo4j_database=os.getenv("NEO4J_DATABASE", "NienLuan2").strip(),
        input_dir=input_dir,
        report_path=PROJECT_DIR / "import_report.json",
        embedding_model_name=os.getenv(
            "EMBEDDING_MODEL_NAME", "BAAI/bge-m3"
        ).strip(),
        embedding_device=os.getenv("EMBEDDING_DEVICE", "cpu").strip(),
        embedding_dimension=int(os.getenv("EMBEDDING_DIMENSION", "1024")),
        embedding_batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "16")),
    )
