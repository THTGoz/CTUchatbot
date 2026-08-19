from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import Event
from .rules import (
    clean_text,
    looks_like_document_start,
    looks_like_table_document_start,
    parse_section,
    titles_overlap,
)


class DocumentLexer:
    """Convert the flat step-04 content list into parser events."""

    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document

    def run(self) -> list[Event]:
        raw_items = self.document.get("noi_dung", [])
        if not isinstance(raw_items, list):
            raise TypeError('Trường "noi_dung" của Bước 04 phải là danh sách.')

        events: list[Event] = [Event("START_DOCUMENT")]
        current_document_has_content = False
        just_started_document = True
        last_text = ""
        current_document_title = ""
        in_numbered_note_block = False

        for index, item in enumerate(raw_items, start=1):
            if not isinstance(item, dict):
                raise TypeError(f'Phần tử noi_dung[{index}] phải là object JSON.')

            item_type = clean_text(item.get("loai")).casefold()

            if item_type == "van_ban":
                text = clean_text(item.get("noi_dung"))
                if not text:
                    continue

                kind = clean_text(item.get("dang"))
                kind_key = kind.casefold()

                if kind_key == "ghi_chu" and text.casefold().startswith(("lưu ý", "ghi chú", "chú thích")):
                    in_numbered_note_block = True

                section = parse_section(text)
                if in_numbered_note_block and kind_key != "heading":
                    section = None

                if section is not None:
                    in_numbered_note_block = False
                    symbol, level = section
                    events.append(Event("START_SECTION", text=text, ky_hieu=symbol, cap=level))
                    current_document_has_content = True
                    just_started_document = False
                    last_text = text
                    continue

                if looks_like_document_start(text, kind):
                    in_numbered_note_block = False
                    if current_document_has_content and not just_started_document:
                        events.append(Event("START_DOCUMENT", text=text))
                        current_document_has_content = False
                    events.append(Event("TEXT", text=text))
                    current_document_title = text
                    current_document_has_content = True
                    just_started_document = False
                    last_text = text
                    continue

                events.append(Event("TEXT", text=text))
                current_document_has_content = True
                just_started_document = False
                last_text = text
                continue

            if item_type == "bang":
                table = deepcopy(item)
                table.pop("loai", None)
                title = clean_text(table.get("tieu_de_bang"))

                title_already_emitted = bool(
                    title
                    and (
                        titles_overlap(last_text, title)
                        or titles_overlap(current_document_title, title)
                    )
                )

                if (
                    looks_like_table_document_start(title)
                    and current_document_has_content
                    and not just_started_document
                    and not title_already_emitted
                ):
                    events.append(Event("START_DOCUMENT", text=title))
                    current_document_has_content = False
                    just_started_document = True

                    if title:
                        events.append(Event("TEXT", text=title))
                        current_document_has_content = True
                        just_started_document = False
                        last_text = title
                        current_document_title = title
                        # The title is represented as text; avoid duplicating it
                        # inside the table object.
                        table["tieu_de_bang"] = ""

                events.append(Event("TABLE", bang=table))
                current_document_has_content = True
                just_started_document = False
                continue

            raise ValueError(
                f'Không hỗ trợ loai tại noi_dung[{index}]: {item_type or "<rỗng>"}'
            )

        return events
