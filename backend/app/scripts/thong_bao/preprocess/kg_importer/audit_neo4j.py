from __future__ import annotations

import json

from neo4j import GraphDatabase

from .config import load_settings


NEW_LABELS = ["ThongBao", "TaiLieu", "Muc", "Bang", "DongBang"]
ALLOWED_PROPERTIES = {
    "ThongBao": [
        "id",
        "ten_file",
        "tieu_de",
        "ma_van_ban",
        "ngay_ban_hanh",
        "loai_thong_bao",
        "nam_ban_hanh",
        "hoc_ky",
        "nam_hoc",
        "nam_hoc_bat_dau",
        "nam_hoc_ket_thuc",
    ],
    "TaiLieu": ["id", "thu_tu", "ten_tai_lieu"],
    "Muc": ["id", "ky_hieu", "noi_dung", "text", "embedding"],
    "Bang": ["id", "thu_tu", "tieu_de", "cot"],
    "DongBang": [
        "id",
        "thu_tu",
        "gia_tri",
        "noi_dung_dong",
        "text",
        "embedding",
    ],
}


def keyed(records, key: str, value: str) -> dict[str, int]:
    return {record[key]: int(record[value]) for record in records}


def count_one(session, query: str, **parameters) -> int:
    record = session.run(query, **parameters).single()
    return int(record["total"]) if record else 0


def main() -> int:
    settings = load_settings()
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    )

    result: dict[str, object] = {"database": settings.neo4j_database}
    try:
        with driver.session(database=settings.neo4j_database) as session:
            result["nodes"] = keyed(
                session.run(
                    """
                    MATCH (n)
                    UNWIND labels(n) AS label
                    WITH n, label
                    WHERE label IN $labels
                    RETURN label, count(n) AS total
                    ORDER BY label
                    """,
                    labels=NEW_LABELS,
                ),
                "label",
                "total",
            )
            result["relationships"] = keyed(
                session.run(
                    """
                    MATCH ()-[r]->()
                    WITH type(r) AS rel_type, count(r) AS total
                    WHERE rel_type IN [
                        'CO_TAI_LIEU', 'CO_MUC', 'CO_BANG', 'CO_DONG'
                    ]
                    RETURN rel_type, total
                    ORDER BY rel_type
                    """
                ),
                "rel_type",
                "total",
            )
            result["orphans"] = {
                "TaiLieu": count_one(session, """
                    MATCH (n:TaiLieu)
                    WHERE NOT (:ThongBao)-[:CO_TAI_LIEU]->(n)
                    RETURN count(n) AS total
                """),
                "Muc": count_one(session, """
                    MATCH (n:Muc) WHERE NOT ()-[:CO_MUC]->(n)
                    RETURN count(n) AS total
                """),
                "Bang": count_one(session, """
                    MATCH (n:Bang) WHERE NOT (:Muc)-[:CO_BANG]->(n)
                    RETURN count(n) AS total
                """),
                "DongBang": count_one(session, """
                    MATCH (n:DongBang) WHERE NOT (:Bang)-[:CO_DONG]->(n)
                    RETURN count(n) AS total
                """),
            }
            result["missing_required"] = {
                "ThongBao": count_one(session, """
                    MATCH (n:ThongBao)
                    WHERE n.id IS NULL OR trim(n.id) = ''
                       OR n.ten_file IS NULL OR trim(n.ten_file) = ''
                       OR n.tieu_de IS NULL
                    RETURN count(n) AS total
                """),
                "TaiLieu": count_one(session, """
                    MATCH (n:TaiLieu)
                    WHERE n.id IS NULL OR n.thu_tu IS NULL
                       OR n.ten_tai_lieu IS NULL OR trim(n.ten_tai_lieu) = ''
                    RETURN count(n) AS total
                """),
                "Muc": count_one(session, """
                    MATCH (n:Muc)
                    WHERE n.id IS NULL OR n.ky_hieu IS NULL
                       OR n.noi_dung IS NULL
                       OR n.text IS NULL OR trim(n.text) = ''
                    RETURN count(n) AS total
                """),
                "Bang": count_one(session, """
                    MATCH (n:Bang)
                    WHERE n.id IS NULL OR n.thu_tu IS NULL
                       OR n.tieu_de IS NULL OR n.cot IS NULL
                    RETURN count(n) AS total
                """),
                "DongBang": count_one(session, """
                    MATCH (n:DongBang)
                    WHERE n.id IS NULL OR n.thu_tu IS NULL
                       OR n.gia_tri IS NULL OR n.noi_dung_dong IS NULL
                       OR n.text IS NULL OR trim(n.text) = ''
                    RETURN count(n) AS total
                """),
            }
            result["source_quality"] = {
                "ThongBao.blank_tieu_de": count_one(session, """
                    MATCH (n:ThongBao)
                    WHERE n.tieu_de IS NOT NULL AND trim(n.tieu_de) = ''
                    RETURN count(n) AS total
                """),
            }
            result["missing_embeddings"] = {
                label: count_one(
                    session,
                    f"""
                    MATCH (n:{label})
                    WHERE n.text IS NOT NULL AND trim(n.text) <> ''
                      AND n.embedding IS NULL
                    RETURN count(n) AS total
                    """,
                )
                for label in ("Muc", "DongBang")
            }
            result["unexpected_properties"] = {
                label: count_one(
                    session,
                    f"""
                    MATCH (n:{label})
                    WHERE any(property IN keys(n) WHERE NOT property IN $allowed)
                    RETURN count(n) AS total
                    """,
                    allowed=allowed,
                )
                for label, allowed in ALLOWED_PROPERTIES.items()
            }
            result["constraints"] = [
                record["name"]
                for record in session.run(
                    """
                    SHOW CONSTRAINTS YIELD name, labelsOrTypes
                    WHERE any(label IN labelsOrTypes WHERE label IN $labels)
                    RETURN name ORDER BY name
                    """,
                    labels=NEW_LABELS,
                )
            ]
            result["vector_indexes"] = [
                dict(record)
                for record in session.run(
                    """
                    SHOW INDEXES YIELD name, type, labelsOrTypes, properties
                    WHERE type = 'VECTOR'
                      AND any(label IN labelsOrTypes WHERE label IN $labels)
                    RETURN name, labelsOrTypes, properties
                    ORDER BY name
                    """,
                    labels=NEW_LABELS,
                )
            ]
            result["sample_hierarchy"] = [
                dict(record)
                for record in session.run(
                    """
                    MATCH (tb:ThongBao)-[:CO_TAI_LIEU]->(tl:TaiLieu)
                          -[:CO_MUC]->(m:Muc)
                    OPTIONAL MATCH (m)-[:CO_BANG]->(b:Bang)
                                      -[:CO_DONG]->(row:DongBang)
                    RETURN tb.id AS thong_bao,
                           tl.thu_tu AS thu_tu_tai_lieu,
                           tl.ten_tai_lieu AS tai_lieu,
                           m.ky_hieu AS muc,
                           b.thu_tu AS thu_tu_bang,
                           b.tieu_de AS bang,
                           row.thu_tu AS thu_tu_dong
                    LIMIT 5
                    """
                )
            ]

        with driver.session(database="system") as system_session:
            result["available_databases"] = [
                {
                    "name": record["name"],
                    "status": record["currentStatus"],
                }
                for record in system_session.run(
                    """
                    SHOW DATABASES YIELD name, currentStatus
                    RETURN name, currentStatus ORDER BY name
                    """
                )
            ]
    finally:
        driver.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
