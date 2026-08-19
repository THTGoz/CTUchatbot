from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.orchestrator import chat_orchestrator

router = APIRouter()


class MessagePart(BaseModel):
    type: str = "text"
    text: str


class MessageItem(BaseModel):
    id: Optional[str] = None
    role: str
    parts: List[MessagePart]


class ChatRequest(BaseModel):
    # Payload đơn giản cho backend/test.
    message: Optional[str] = None
    history: List[dict] = Field(default_factory=list)

    # Payload của frontend main (Vercel AI stream style).
    id: Optional[str] = None
    messages: Optional[List[MessageItem]] = None
    trigger: Optional[str] = None


def _extract_request(req: ChatRequest) -> tuple[str, List[dict]]:
    message = (req.message or "").strip()
    history = list(req.history or [])
    if message or not req.messages:
        return message, history

    user_messages = [item for item in req.messages if item.role == "user" and item.parts]
    if user_messages:
        message = (user_messages[-1].parts[0].text or "").strip()

    history = []
    for item in req.messages[:-1]:
        if not item.parts:
            continue
        content = (item.parts[0].text or "").strip()
        if content:
            history.append({"role": item.role, "content": content})
    return message, history


@router.post("/chat")
async def chat(req: ChatRequest):
    message, history = _extract_request(req)
    result = await chat_orchestrator.handle_query(message, history)
    answer = str(result.get("answer", "")).strip()
    if not answer:
        answer = "Mình chưa tìm thấy đủ dữ liệu để trả lời chính xác."

    async def stream_results():
        # Frontend main đang đọc Vercel AI data stream: mỗi text chunk bắt đầu bằng `0:`.
        yield f"0:{json.dumps(answer, ensure_ascii=False)}\n"

    return StreamingResponse(
        stream_results(),
        media_type="text/plain",
        headers={"X-Vercel-AI-Data-Stream": "v1"},
    )
