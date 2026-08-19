from __future__ import annotations

from copy import deepcopy
from typing import Any

from .rules import clean_text


class StructureValidator:
    def normalize(self, result: dict[str, Any]) -> dict[str, Any]:
        metadata = result.get("metadata", {})
        documents = result.get("tai_lieu", [])

        if not isinstance(metadata, dict):
            raise TypeError('Trường "metadata" phải là object JSON.')
        if not isinstance(documents, list):
            raise TypeError('Trường "tai_lieu" phải là danh sách.')

        return {
            "metadata": deepcopy(metadata),
            "tai_lieu": [
                self._normalize_document(
                    document,
                    index,
                    clean_text(metadata.get("tieu_de")),
                )
                for index, document in enumerate(documents, start=1)
            ],
        }

    def _normalize_document(
        self,
        document: Any,
        index: int,
        notice_title: str,
    ) -> dict[str, Any]:
        if not isinstance(document, dict):
            raise TypeError(f"tai_lieu[{index}] phải là object JSON.")

        sections = document.get("muc", [])
        if not isinstance(sections, list):
            raise TypeError(f'tai_lieu[{index}].muc phải là danh sách.')

        document_title = clean_text(document.get("ten_tai_lieu"))
        if not document_title and index == 1:
            document_title = notice_title

        return {
            "id": clean_text(document.get("id")) or f"doc_{index}",
            "thu_tu": index,
            "ten_tai_lieu": document_title or f"Tài liệu {index}",
            "muc": [
                self._normalize_section(section, f"tai_lieu[{index}].muc[{position}]")
                for position, section in enumerate(sections, start=1)
            ],
        }

    def _normalize_section(self, section: Any, path: str) -> dict[str, Any]:
        if not isinstance(section, dict):
            raise TypeError(f"{path} phải là object JSON.")

        texts = section.get("noi_dung", [])
        tables = section.get("bang", [])
        children = section.get("muc_con", [])

        if not isinstance(texts, list):
            raise TypeError(f"{path}.noi_dung phải là danh sách.")
        if not isinstance(tables, list):
            raise TypeError(f"{path}.bang phải là danh sách.")
        if not isinstance(children, list):
            raise TypeError(f"{path}.muc_con phải là danh sách.")

        normalized_texts = [clean_text(text) for text in texts]
        normalized_texts = [text for text in normalized_texts if text]

        normalized_tables: list[dict[str, Any]] = []
        for table_index, table in enumerate(tables, start=1):
            if not isinstance(table, dict):
                raise TypeError(f"{path}.bang[{table_index}] phải là object JSON.")
            normalized_tables.append(self._normalize_table(table, f"{path}.bang[{table_index}]"))

        return {
            "id": clean_text(section.get("id")),
            "ky_hieu": clean_text(section.get("ky_hieu")),
            "noi_dung": normalized_texts,
            "bang": normalized_tables,
            "muc_con": [
                self._normalize_section(child, f"{path}.muc_con[{index}]")
                for index, child in enumerate(children, start=1)
            ],
        }

    def _normalize_table(self, table: dict[str, Any], path: str) -> dict[str, Any]:
        columns = table.get("cot", [])
        rows = table.get("du_lieu", [])

        if not isinstance(columns, list):
            raise TypeError(f"{path}.cot phải là danh sách.")
        if not isinstance(rows, list):
            raise TypeError(f"{path}.du_lieu phải là danh sách.")

        normalized_rows: list[list[str]] = []
        for row_index, row in enumerate(rows, start=1):
            if not isinstance(row, list):
                raise TypeError(f"{path}.du_lieu[{row_index}] phải là danh sách.")
            normalized_rows.append([clean_text(cell) for cell in row])

        return {
            "tieu_de_bang": clean_text(table.get("tieu_de_bang")),
            "cot": [clean_text(column) for column in columns],
            "du_lieu": normalized_rows,
        }
