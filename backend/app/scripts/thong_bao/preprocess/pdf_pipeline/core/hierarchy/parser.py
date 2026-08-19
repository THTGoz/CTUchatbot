from __future__ import annotations

import re
from copy import deepcopy

from .models import Event, LogicalDocument, SectionNode
from .rules import clean_text


class HierarchyParser:
    def __init__(self, events: list[Event]) -> None:
        self.events = events
        self.documents: list[LogicalDocument] = []
        self.current_document: LogicalDocument | None = None
        self.section_stack: list[tuple[int, SectionNode]] = []
        self.unnamed_counts: dict[str, int] = {}

    def run(self) -> list[LogicalDocument]:
        for event in self.events:
            if event.loai == "START_DOCUMENT":
                self._start_document(event.text)
            elif event.loai == "START_SECTION":
                self._start_section(event)
            elif event.loai == "TEXT":
                self._append_text(event.text)
            elif event.loai == "TABLE":
                self._append_table(event.bang or {})
            else:
                raise ValueError(f"Event không được hỗ trợ: {event.loai}")

        return [document for document in self.documents if document.muc]

    def _start_document(self, title: str = "") -> None:
        document = LogicalDocument(
            id=f"doc_{len(self.documents) + 1}",
            thu_tu=len(self.documents) + 1,
            ten_tai_lieu=clean_text(title),
        )
        self.documents.append(document)
        self.current_document = document
        self.section_stack = []

    def _require_document(self) -> LogicalDocument:
        if self.current_document is None:
            self._start_document()
        assert self.current_document is not None
        return self.current_document

    @staticmethod
    def _safe_symbol(symbol: str) -> str:
        value = clean_text(symbol).casefold()
        value = re.sub(r"^bước\s+", "buoc_", value)
        value = re.sub(r"[^a-z0-9à-ỹđ]+", "_", value, flags=re.UNICODE)
        return value.strip("_") or "0"

    def _new_section_id(self, symbol: str) -> str:
        document = self._require_document()
        base = f"{document.id}_muc_{self._safe_symbol(symbol)}"

        if symbol:
            existing = self._collect_ids(document.muc)
            if base not in existing:
                return base
            suffix = 2
            while f"{base}_{suffix}" in existing:
                suffix += 1
            return f"{base}_{suffix}"

        count = self.unnamed_counts.get(document.id, 0) + 1
        self.unnamed_counts[document.id] = count
        return base if count == 1 else f"{base}_{count}"

    def _collect_ids(self, nodes: list[SectionNode]) -> set[str]:
        result: set[str] = set()
        for node in nodes:
            result.add(node.id)
            result.update(self._collect_ids(node.muc_con))
        return result

    def _ensure_unnamed_section(self) -> SectionNode:
        document = self._require_document()

        if self.section_stack:
            return self.section_stack[-1][1]

        if document.muc and not document.muc[-1].ky_hieu:
            node = document.muc[-1]
        else:
            node = SectionNode(id=self._new_section_id(""), ky_hieu="")
            document.muc.append(node)

        self.section_stack = [(1, node)]
        return node

    def _start_section(self, event: Event) -> None:
        document = self._require_document()
        level = max(1, int(event.cap or 1))
        node = SectionNode(
            id=self._new_section_id(event.ky_hieu),
            ky_hieu=clean_text(event.ky_hieu),
        )

        heading = clean_text(event.text)
        if heading:
            node.noi_dung.append(heading)

        while self.section_stack and self.section_stack[-1][0] >= level:
            self.section_stack.pop()

        if level > 1 and self.section_stack:
            self.section_stack[-1][1].muc_con.append(node)
        else:
            document.muc.append(node)
            level = 1

        self.section_stack.append((level, node))

    def _append_text(self, text: str) -> None:
        value = clean_text(text)
        if not value:
            return
        node = self._ensure_unnamed_section()
        node.noi_dung.append(value)

    def _append_table(self, table: dict) -> None:
        node = self._ensure_unnamed_section()
        node.bang.append(deepcopy(table))
