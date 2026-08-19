import logging
import os
import re
import requests
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger("app.quyche_llm")


def _load_env_files() -> None:
    backend_root = Path(__file__).resolve().parents[3]
    repo_root = backend_root.parent
    load_dotenv(backend_root / ".env", override=False)
    load_dotenv(repo_root / ".env", override=False)


def _get_env(*keys: str, default: str) -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return default


_load_env_files()

OLLAMA_BASE_URL = _get_env("OLLAMA_BASE_URL", "OLLAMA_HOST", default="http://localhost:11434").rstrip("/")
OLLAMA_GENERATE_URL = os.getenv("OLLAMA_GENERATE_URL", f"{OLLAMA_BASE_URL}/api/generate")
OLLAMA_CHAT_URL = os.getenv("OLLAMA_CHAT_URL", f"{OLLAMA_BASE_URL}/api/chat")
DEFAULT_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
MODEL_PRIMARY_9B = _get_env("QWEN3_5_MODEL_9B", "OLLAMA_MODEL_9B", default="qwen3.5:9b")
MODEL_AUX_7B = _get_env("QWEN2_5_MODEL_7B", "OLLAMA_MODEL_7B", default="qwen2.5-coder:7b-instruct")
MODEL_AUX_4B = _get_env("QWEN3_5_MODEL_4B", "OLLAMA_MODEL_4B", default="qwen3.5:4b")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")

VANBAN_MAP = {
    "quychehocvu":            "quychehocvu",
    "quydinhdaotaotructuyen": "quydinhdaotaotructuyen",
    "QCDTVHVL":               "QCDTVHVL",
    "QCDTTuXa":              "QCDTTuXa",
}

VANBAN_DISPLAY = {
    "quychehocvu":            "Quy chế Học vụ",
    "quydinhdaotaotructuyen": "Quy định Đào tạo Trực tuyến",
    "QCDTVHVL":               "Quy chế Đào tạo Vừa học vừa làm",
    "QCDTTuXa":               "Quy chế Đào tạo Từ xa",
}

VANBAN_KEYWORDS = {
    "quydinhdaotaotructuyen": ["trực tuyến", "online", "e-learning", "đào tạo trực tuyến"],
    "QCDTVHVL":               ["vừa học vừa làm", "vhvl", "tại chức", "hệ vừa học"],
    "QCDTTuXa":               ["từ xa", "đào tạo từ xa", "hệ từ xa"],
}

VANBAN_CLASSIFY_SYSTEM = """Bạn là hệ thống phân loại văn bản quy chế đào tạo của Đại học Cần Thơ (CTU).
## Nhiệm vụ:
Dựa vào câu hỏi, phân loại văn bản quy chế đào tạo liên quan nhất mà người hỏi đang đề cập tới, dựa trên 4 loại văn bản sau:
1. quychehocvu       — Quy chế Học vụ (hệ chính quy)
2. quydinhdaotaotructuyen — Đào tạo Trực tuyến / online / e-learning
3. QCDTVHVL          — Đào tạo Vừa học vừa làm / tại chức
4. QCDTTuXa          — Đào tạo Từ xa

## Ví dụ:
- "Điều 9 Khoản 1 Điểm a của Quy chế Học vụ" → quychehocvu
- "Quy định về đào tạo trực tuyến" → quydinhdaotaotructuyen
- "Tôi muốn hỏi về hệ vừa học vừa làm" → QCDTVHVL
- "Tôi muốn hỏi về đào tạo từ xa" → QCDTTuXa
- "Quy định về học online" → quydinhdaotaotructuyen
- "Tôi muốn học từ xa" → QCDTTuXa
- "Quy định về việc vừa làm vừa học" → QCDTVHVL

## Nguyên tắc:
- Dựa vào câu hỏi, chỉ trả về 1 trong 4 giá trị trên, KHÔNG giải thích.
- Nếu không chắc chắn, hãy chọn loại văn bản mà bạn nghĩ người hỏi đang đề cập tới nhất, nhưng vẫn CHỈ trả về 1 trong 4 giá trị trên, KHÔNG giải thích.
"""

PREPROCESS_SYSTEM = """Bạn là công cụ CHUẨN HÓA văn bản, KHÔNG phải trợ lý giải đáp.
## Nhiệm vụ:
1. Sửa lỗi chính tả, gõ phím, thiếu dấu tiếng Việt.
2. CHỈ đổi số sau từ "Chương" sang số La Mã. VD: "chương 1" → "Chương I".
3. GIỮ NGUYÊN số sau Điều và Khoản (số Ả-rập). VD: "Điều 9", "Khoản 1".
4. GIỮ NGUYÊN chữ cái sau Điểm. VD: "Điểm a".
5. KHÔNG tự ý thay đổi ý nghĩa câu hỏi.
Chỉ trả về đúng 1 dòng là câu đã chuẩn hóa."""

ANSWER_SYSTEM = """Bạn là trợ lý tư vấn đào tạo Đại học Cần Thơ (CTU).

## Nhiệm vụ
CHỈ trả lời câu hỏi dựa trên NỘI DUNG ĐƯỢC CUNG CẤP.

## Quy tắc bắt buộc
- Chỉ sử dụng thông tin trong CONTEXT, không dùng kiến thức bên ngoài và không suy đoán.
- Trả lời đúng phần người dùng hỏi; KHÔNG tóm tắt toàn bộ điều/khoản hoặc mọi trường hợp có trong context.
- Với câu hỏi đơn giản, ưu tiên 1-3 câu ngắn.
- Chỉ dùng bullet khi câu hỏi thực sự cần liệt kê nhiều điều kiện, trường hợp hoặc bước.
- Nếu có ngoại lệ nhưng không liên quan trực tiếp đến câu hỏi thì không tự mở rộng sang ngoại lệ đó.
- Nếu context không đủ, nói ngắn gọn rằng chưa đủ thông tin; chỉ khuyên liên hệ Phòng Đào tạo khi thực sự cần.
- Nếu có tên văn bản nguồn, nêu tên nguồn một lần ngắn gọn; không mở đầu bằng đoạn dẫn dài.
- Với GPA/điểm trung bình/xếp loại, chỉ dùng đúng thang điểm và bảng quy đổi xuất hiện trong context.
- Không thêm lời mời hỏi tiếp hoặc kết luận chung nếu người dùng không yêu cầu.

Mục tiêu là câu trả lời ngắn, chính xác, bám sát câu hỏi.
"""

class QuyCheLLMService:
    def __init__(self) -> None:
        self.model_primary = MODEL_PRIMARY_9B
        self.timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    def _call_llm(
        self,
        messages: list,
        temperature: float = 0.1,
        *,
        num_predict: int = 512,
    ) -> str:
        url = OLLAMA_CHAT_URL
        payload = {
            "model": self.model_primary,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": "1h",
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
            },
        }
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout_seconds)
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()
        except Exception as e:
            logger.error(f"[QuyCheLLM] Lỗi gọi Ollama: {e}")
            return ""

    def preprocess_question(self, raw: str) -> str:
        msgs = [
            {"role": "system", "content": PREPROCESS_SYSTEM},
            {"role": "user",   "content": raw.strip()},
        ]
        result = self._call_llm(msgs, temperature=0.0, num_predict=128)
        if not result or len(result) > 500:
            return raw
        return result.strip()

    def detect_vanban(self, question: str) -> str:
        q_lower = question.lower()
        
        # Thử keyword trước
        for vb_key, keywords in VANBAN_KEYWORDS.items():
            for kw in keywords:
                if kw in q_lower:
                    result = VANBAN_MAP[vb_key]
                    logger.info(f"[QuyCheLLM] detect_vanban: keyword match '{kw}' -> {result} (question: {question[:50]}...)")
                    return result
        
        # Gọi LLM nếu không match keyword
        msgs = [
            {"role": "system", "content": VANBAN_CLASSIFY_SYSTEM},
            {"role": "user",   "content": question},
        ]
        raw_out = self._call_llm(msgs, temperature=0.0, num_predict=32).strip().lower()
        for key in VANBAN_MAP:
            if key in raw_out:
                result = VANBAN_MAP[key]
                logger.info(f"[QuyCheLLM] detect_vanban: LLM classify '{raw_out}' -> {result} (question: {question[:50]}...)")
                return VANBAN_MAP[key]
        
        default_result = VANBAN_MAP["quychehocvu"]
        logger.info(f"[QuyCheLLM] detect_vanban: fallback -> {default_result} (question: {question[:50]}...)")
        return default_result

    def generate_answer(self, question: str, context: str, history: list, vb_display: str = "") -> str:
        history_msgs = history[-6:]
        source_note = f"\nNguồn: {vb_display}" if vb_display else ""
        user_content = (
            f"Câu hỏi: {question}\n\n"
            f"Nội dung từ văn bản quy chế:{source_note}\n"
            "---\n"
            f"{context if context else '(Không tìm thấy nội dung liên quan — hãy thông báo cho sinh viên liên hệ phòng Đào tạo)'}\n"
            "---\n\n"
            "Hãy trả lời câu hỏi trên."
        )
        messages = (
            [{"role": "system", "content": ANSWER_SYSTEM}]
            + history_msgs
            + [{"role": "user", "content": user_content}]
        )
        return self._call_llm(messages, temperature=0.2, num_predict=256)


quyche_llm_service = QuyCheLLMService()
