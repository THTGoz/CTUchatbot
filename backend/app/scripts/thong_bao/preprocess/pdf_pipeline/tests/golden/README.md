# Golden master cho PDF Thông báo

Thư mục này giữ đúng **một JSON cuối cho mỗi loại thông báo hiện có**:

- `dang_ky_hoc_phan.json`
- `diem_ren_luyen.json`
- `lich_nghi.json`
- `chuyen_nganh.json`
- `xoa_lop_hoc_phan.json`

Các file là đầu ra đã có trước khi sắp xếp lại source. Chúng không được dùng
trong production; chúng chỉ phát hiện thay đổi ngoài ý muốn ở bước 02–06.

Từ thư mục `backend`, chạy:

```powershell
python -m app.scripts.thong_bao.preprocess.pdf_pipeline.verify_golden
```

Chỉ cập nhật golden master khi thay đổi output là có chủ đích và đã được duyệt.
