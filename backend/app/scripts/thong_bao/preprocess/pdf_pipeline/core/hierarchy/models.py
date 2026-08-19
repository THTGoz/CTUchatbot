from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SectionNode:
    id: str
    ky_hieu: str = ""
    noi_dung: list[str] = field(default_factory=list)
    bang: list[dict[str, Any]] = field(default_factory=list)
    muc_con: list["SectionNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ky_hieu": self.ky_hieu,
            "noi_dung": list(self.noi_dung),
            "bang": deepcopy(self.bang),
            "muc_con": [child.to_dict() for child in self.muc_con],
        }


@dataclass
class LogicalDocument:
    id: str
    thu_tu: int
    ten_tai_lieu: str = ""
    muc: list[SectionNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thu_tu": self.thu_tu,
            "ten_tai_lieu": self.ten_tai_lieu,
            "muc": [section.to_dict() for section in self.muc],
        }


@dataclass(frozen=True)
class Event:
    loai: str
    text: str = ""
    ky_hieu: str = ""
    cap: int = 0
    bang: dict[str, Any] | None = None
