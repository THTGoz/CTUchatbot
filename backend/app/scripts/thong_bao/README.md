# Scripts Thông báo

Thư mục gồm:

- `debug.py`: kiểm tra retrieval/runtime pipeline;
- `preprocess/pdf_pipeline/`: chuyển PDF thành chunks JSON;
- `preprocess/kg_importer/`: nhập chunks và embedding vào Neo4j.

Chạy debug độc lập từ thư mục `CITchatbotv2/backend`:

```powershell
python -m app.scripts.thong_bao.debug "Khi nào đăng ký học phần HK1?"
```

Script gọi trực tiếp `services/thong_bao/` và không chạy LLM router, CTDT hoặc QCHV.

Hướng dẫn tiền xử lý và import nằm tại `preprocess/README.md`.
