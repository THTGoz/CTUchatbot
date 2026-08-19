"""Model embedding dùng chung cho runtime services và các luồng ingestion."""

from typing import List, Union, Optional
from sentence_transformers import SentenceTransformer
import torch
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(".env")

# Global embedding model instance - khởi tạo 1 lần
_embedding_model: Optional['EmbeddingModel'] = None


def _find_model_path() -> tuple[str, bool]:
    """Trả về (model_path_or_name, local_files_only).

    Ưu tiên EMBEDDING_MODEL_PATH, sau đó cache local của project. Nếu không có,
    dùng tên model Hugging Face để SentenceTransformer tải/cache ở lần chạy đầu.
    """
    configured_path = os.getenv("EMBEDDING_MODEL_PATH", "").strip()
    if configured_path:
        candidate = Path(configured_path).expanduser().resolve()
        if not candidate.exists():
            raise RuntimeError(f"EMBEDDING_MODEL_PATH does not exist: {candidate}")
        return str(candidate), True

    script_dir = Path(__file__).resolve().parent
    # File nằm trong app/services/common nên project root cách thư mục hiện tại bốn cấp.
    project_root = script_dir.parents[3]
    model_root = project_root / "my_model_weights" / "bge_m3" / "models--BAAI--bge-m3"
    snapshots_dir = model_root / "snapshots"

    def _is_valid_snapshot(snapshot_dir: Path) -> bool:
        config_path = snapshot_dir / "config.json"
        modules_path = snapshot_dir / "modules.json"
        weights_path = snapshot_dir / "pytorch_model.bin"
        if not (config_path.exists() and modules_path.exists() and weights_path.exists()):
            return False
        try:
            import json
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return bool(cfg.get("model_type"))
        except Exception:
            return False

    # Ưu tiên commit hash trong refs/main (đúng snapshot mà HF cache đang trỏ tới)
    refs_main = model_root / "refs" / "main"
    if refs_main.exists():
        snapshot_id = refs_main.read_text(encoding="utf-8").strip()
        candidate = snapshots_dir / snapshot_id
        if _is_valid_snapshot(candidate):
            return str(candidate), True

    if snapshots_dir.exists():
        valid_snapshots = [p for p in snapshots_dir.glob("*") if _is_valid_snapshot(p)]
        if valid_snapshots:
            return str(sorted(valid_snapshots)[-1]), True

    return os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3"), False


def get_embedding_model() -> 'EmbeddingModel':
    """Lấy global embedding model instance (tạo 1 lần duy nhất)"""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = EmbeddingModel()
    return _embedding_model


class EmbeddingModel:
    def __init__(self, device=None):
        # Tìm đường dẫn model local
        model_path, local_files_only = _find_model_path()
        
        resolved_device = device or os.getenv("EMBEDDING_DEVICE") or self._detect_best_device()
        self.device = resolved_device
        self.model_name = "BAAI/bge-m3"
        self.model_path = model_path
        
        # Load model từ đường dẫn local dùng SentenceTransformer
        self.model = SentenceTransformer(
            model_path,
            device=resolved_device,
            trust_remote_code=True,
            local_files_only=local_files_only,
        )
        print(
            f"[Startup] Embedding initialized | model={self.model_name} | device={self.device} | path={self.model_path}"
        )

    @staticmethod
    def _detect_best_device() -> str:
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def get_embedding_batch(self, texts: Union[str, List[str]]):
        if isinstance(texts, str):
            texts = [texts]
        
        cleaned_texts = [t.strip() for t in texts if t and t.strip()]
        if not cleaned_texts:
            return []

        embeddings = self.model.encode(cleaned_texts, convert_to_tensor=False)
        return [list(emb) if hasattr(emb, '__iter__') else emb for emb in embeddings]
    
    
