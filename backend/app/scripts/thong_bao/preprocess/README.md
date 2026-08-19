# Tiền xử lý Thông báo

Luồng offline của miền Thông báo gồm hai pipeline độc lập:

```text
PDF
  -> pdf_pipeline (6 bước)
  -> *_chunks.json
  -> kg_importer
  -> ThongBao / TaiLieu / Muc / Bang / DongBang trong Neo4j
```

## 1. PDF thành chunks JSON

Chạy từ thư mục `CITchatbotv2/backend`:

```powershell
python -m app.scripts.thong_bao.preprocess.pdf_pipeline.main
```

Chạy một file PDF và không ghi đè output cũ:

```powershell
python -m app.scripts.thong_bao.preprocess.pdf_pipeline.chay_mot_pdf "D:\TaiLieu\thong_bao.pdf"
```

## 2. Chunks JSON vào Neo4j

Nhập thêm đúng một thông báo mới, không xóa dữ liệu cũ:

```powershell
python -m app.scripts.thong_bao.preprocess.kg_importer.nhap_file_moi "D:\KetQua\thong_bao_chunks.json"
```

Nhập hoặc thay thế riêng các thông báo trong một thư mục:

```powershell
python -m app.scripts.thong_bao.preprocess.kg_importer.nhap_thu_muc "D:\KetQua\06_chunks"
```

Full import toàn bộ output mặc định:

```powershell
python -m app.scripts.thong_bao.preprocess.kg_importer.main
```

**Cảnh báo:** full import sẽ xóa toàn bộ nhánh `ThongBao` cũ trước khi nhập lại.
Khi thêm dữ liệu hằng ngày, ưu tiên `nhap_file_moi` hoặc `nhap_thu_muc`.

Importer đọc Neo4j/model settings từ `CITchatbotv2/backend/.env`.

Schema graph của miền Thông báo:

```text
ThongBao -[:CO_TAI_LIEU]-> TaiLieu(id, thu_tu, ten_tai_lieu)
TaiLieu  -[:CO_MUC]->      Muc(id, ky_hieu, noi_dung, text, embedding)
Muc      -[:CO_MUC]->      Muc
Muc      -[:CO_BANG]->     Bang(id, thu_tu, tieu_de, cot)
Bang     -[:CO_DONG]->     DongBang(id, thu_tu, gia_tri, noi_dung_dong, text, embedding)
```

Sau khi đổi từ schema cũ, chạy cleanup, full import, sinh embedding và audit:

```powershell
cypher-shell -f app/scripts/thong_bao/preprocess/kg_importer/cleanup_old_group_metadata.cypher
python -m app.scripts.thong_bao.preprocess.kg_importer.main
python -m app.scripts.thong_bao.preprocess.kg_importer.embedding.generate_embedding --force
python -m app.scripts.thong_bao.preprocess.kg_importer.audit_neo4j
```
