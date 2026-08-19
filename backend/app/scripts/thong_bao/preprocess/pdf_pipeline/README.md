# Pipeline PDF Thông báo

Thư mục này chỉ xử lý dữ liệu của miền **THONG_BAO**: chuyển PDF thành JSON
có cấu trúc để `kg_importer` nạp vào Neo4j. Pipeline CTDT và QCHV không dùng
source trong thư mục này.

## Cấu trúc

```text
pdf_pipeline/
├── input/                 PDF đầu vào
├── output/                Kết quả batch của sáu bước
├── stages/                Một module dễ đọc cho mỗi bước biến đổi
│   ├── extract_raw.py
│   ├── clean_data.py
│   ├── extract_metadata.py
│   ├── build_document.py
│   ├── build_hierarchy.py
│   └── build_chunks.py
├── core/                  Hàm dùng chung và bộ dựng cây tài liệu
├── tests/golden/          Một JSON chuẩn cho mỗi loại thông báo
├── pipeline.py            Thứ tự bước và logic điều phối dùng chung
├── main.py                Chạy batch các file trong input/
├── chay_mot_pdf.py        Debug một PDF, không đụng output batch
└── verify_golden.py       So sánh output mới với năm JSON chuẩn
```

Sáu thư mục trong `output/` tương ứng trực tiếp với sáu module trong
`stages/`. JSON cuối ở `output/06_chunks/` là đầu vào mặc định của
`kg_importer`.

## Chuẩn bị

Từ thư mục `CITchatbotv2/backend`, cài dependency đọc PDF:

```powershell
python -m pip install -r app/scripts/thong_bao/preprocess/pdf_pipeline/requirements.txt
```

## Chạy batch

```powershell
python -m app.scripts.thong_bao.preprocess.pdf_pipeline.main
```

Chạy lại từ một bước hoặc trong một khoảng bước:

```powershell
python -m app.scripts.thong_bao.preprocess.pdf_pipeline.main --from-step 4
python -m app.scripts.thong_bao.preprocess.pdf_pipeline.main --from-step 2 --to-step 5
```

Chỉ thêm `--clean` khi muốn xóa output của chính các bước được chọn trước khi
chạy. Không có `--clean`, pipeline giữ cách ghi output cũ.

## Debug một PDF

Lệnh dưới đây tạo một thư mục kết quả mới trong `output_single/`, vì vậy không
ghi đè output batch:

```powershell
python -m app.scripts.thong_bao.preprocess.pdf_pipeline.chay_mot_pdf "D:\TaiLieu\thong_bao.pdf"
```

Có thể chỉ định thư mục mới bằng `--output`. Lệnh sẽ từ chối chạy nếu thư mục
đó đã tồn tại.

## Kiểm tra kết quả không đổi

Năm golden master đại diện cho đăng ký học phần, điểm rèn luyện, lịch nghỉ,
chuyển ngành và xóa lớp học phần. Lệnh sau chạy lại bước 02–06 từ JSON thô rồi
so sánh toàn bộ dữ liệu và SHA-256:

```powershell
python -m app.scripts.thong_bao.preprocess.pdf_pipeline.verify_golden
```

Kiểm tra này không cần PyMuPDF. Bước 01 vẫn cần PyMuPDF vì phải đọc PDF thật.
