from __future__ import annotations

"""Kết nối Neo4j dành riêng cho các transaction import Thông báo."""

from collections.abc import Callable
from typing import Any

from neo4j import GraphDatabase, ManagedTransaction

from .config import Settings


CONSTRAINTS = (
    ("thongbao_id_unique", "ThongBao"),
    ("tailieu_id_unique", "TaiLieu"),
    ("muc_id_unique", "Muc"),
    ("bang_id_unique", "Bang"),
    ("dongbang_id_unique", "DongBang"),
)


class Neo4jConnection:
    """Bao bọc driver, constraint và transaction của KG Thông báo."""

    def __init__(self, settings: Settings) -> None:
        """Mở driver theo Settings nhưng chưa thực hiện truy vấn ghi."""
        self.database = settings.neo4j_database
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
        )

    def close(self) -> None:
        """Đóng driver Neo4j sau khi import hoặc khi có lỗi."""
        self.driver.close()

    def verify(self) -> None:
        """Kiểm tra kết nối và quyền truy cập database đích."""
        self.driver.verify_connectivity()
        with self.driver.session(database=self.database) as session:
            session.run("RETURN 1 AS ok").consume()

    def execute_write(
        self,
        callback: Callable[[ManagedTransaction], Any],
    ) -> Any:
        """Chạy callback trong managed write transaction của Neo4j."""
        with self.driver.session(database=self.database) as session:
            return session.execute_write(callback)

    def create_constraints(self) -> None:
        """Tạo unique constraint cho năm loại node của nhánh Thông báo."""
        with self.driver.session(database=self.database) as session:
            for name, label in CONSTRAINTS:
                session.run(
                    f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
                ).consume()

    def delete_thongbao_branch(self) -> int:
        """Xóa toàn bộ nhánh Thông báo; chỉ được dùng trong full import."""
        query = """
        MATCH (tb:ThongBao)
        OPTIONAL MATCH (tb)-[
            :CO_TAI_LIEU|CO_MUC|CO_BANG|CO_DONG*0..
        ]->(descendant)
        WITH collect(DISTINCT tb) + collect(DISTINCT descendant) AS nodes
        UNWIND nodes AS node
        WITH DISTINCT node
        DETACH DELETE node
        RETURN count(node) AS deleted_count
        """
        with self.driver.session(database=self.database) as session:
            record = session.run(query).single()
            return int(record["deleted_count"]) if record else 0
