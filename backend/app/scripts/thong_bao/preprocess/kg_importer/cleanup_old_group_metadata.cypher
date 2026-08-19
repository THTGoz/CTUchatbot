// Chạy một lần khi chuyển KG Thông báo hiện tại sang schema gọn.
// Các property mới (ten_tai_lieu, ky_hieu, Bang.thu_tu) cần full import để có dữ liệu đúng.
DROP INDEX vector_muc_embedding IF EXISTS;
DROP INDEX vector_dongbang_embedding IF EXISTS;
DROP INDEX vector_bang_embedding IF EXISTS;

MATCH (tl:TaiLieu)
REMOVE tl.path;

MATCH (m:Muc)
REMOVE m.path;

MATCH (b:Bang)
REMOVE b.path, b.text, b.embedding, b.vi_tri_cot_nhom_chinh;

MATCH (d:DongBang)
REMOVE d.path,
       d.danh_sach_ma_hoc_phan,
       d.ma_hoc_phan,
       d.khoa,
       d.khoa_so,
       d.cot_nhom_chinh,
       d.gia_tri_nhom_chinh;
