"""Sinh embedding cho các node Muc và DongBang."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase


PROJECT_DIR = Path(__file__).resolve().parents[1]

from ..config import load_settings


NODE_LABELS = ("Muc", "DongBang")


# Đọc tham số dòng lệnh cho tác vụ sinh embedding.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sinh embedding BGE-M3 cho KG ThongBao."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Sinh lại cả những node đã có embedding.",
    )
    return parser.parse_args()


# Tải các node cần sinh mới hoặc sinh lại embedding.
def load_nodes(session, label: str, force: bool) -> list[dict[str, str]]:
    condition = "" if force else "AND n.embedding IS NULL"
    query = f"""
    MATCH (n:{label})
    WHERE n.text IS NOT NULL AND trim(n.text) <> '' {condition}
    RETURN n.id AS id, n.text AS text
    ORDER BY n.id
    """
    return [dict(record) for record in session.run(query)]


# Ghi một batch embedding trở lại Neo4j.
def save_embeddings(session, label: str, rows: list[dict]) -> None:
    session.run(
        f"""
        UNWIND $rows AS row
        MATCH (n:{label} {{id: row.id}})
        SET n.embedding = row.embedding
        """,
        rows=rows,
    ).consume()



# Chạy toàn bộ quy trình sinh embedding và ghi báo cáo.
def main() -> int:
    from sentence_transformers import SentenceTransformer

    args = parse_args()
    settings = load_settings()
    report: dict[str, object] = {
        "started_at": datetime.now().astimezone().isoformat(),
        "database": settings.neo4j_database,
        "model": settings.embedding_model_name,
        "dimension": settings.embedding_dimension,
        "device": settings.embedding_device,
        "force": args.force,
        "nodes": {},
    }

    print(f"Đang nạp model {settings.embedding_model_name}...")
    model = SentenceTransformer(
        settings.embedding_model_name,
        device=settings.embedding_device,
    )
    model_dimension = model.get_sentence_embedding_dimension()
    if model_dimension != settings.embedding_dimension:
        raise ValueError(
            f"Model trả về {model_dimension} chiều, "
            f"cấu hình cần {settings.embedding_dimension} chiều."
        )

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    )
    try:
        driver.verify_connectivity()
        with driver.session(database=settings.neo4j_database) as session:
            for label in NODE_LABELS:
                nodes = load_nodes(session, label, args.force)
                print(f"{label}: cần sinh {len(nodes)} embedding")
                completed = 0
                for start in range(0, len(nodes), settings.embedding_batch_size):
                    batch = nodes[start : start + settings.embedding_batch_size]
                    vectors = model.encode(
                        [node["text"] for node in batch],
                        batch_size=settings.embedding_batch_size,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    )
                    rows = [
                        {"id": node["id"], "embedding": vector.tolist()}
                        for node, vector in zip(batch, vectors, strict=True)
                    ]
                    save_embeddings(session, label, rows)
                    completed += len(rows)
                    print(f"  Đã ghi {completed}/{len(nodes)}")
                report["nodes"][label] = completed


            report["verification"] = [
                dict(record)
                for record in session.run(
                    """
                    MATCH (n)
                    WHERE n:Muc OR n:DongBang
                    RETURN labels(n)[0] AS label, count(*) AS total,
                           count(n.embedding) AS embedded,
                           collect(DISTINCT size(n.embedding)) AS dimensions
                    ORDER BY label
                    """
                )
            ]
    finally:
        driver.close()

    report["finished_at"] = datetime.now().astimezone().isoformat()
    report_path = PROJECT_DIR / "embedding_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Hoàn tất. Báo cáo: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
