# Bộ 5 câu hỏi Thông báo cần nhiều node

Đây là bản mô tả riêng của 5 case tổng hợp nhiều evidence. Năm case này cũng được đưa vào
benchmark chính trong `notification_qa_30.json` dưới nhóm `Multi-node`.

## Quy tắc evidence

Mỗi câu có ít nhất hai `evidence_groups`. Tất cả group đều bắt buộc (`ALL_GROUPS`), còn
các node trong cùng một group là tương đương (`ANY_OF`). Một câu chỉ đạt evidence coverage
khi final bundle chứa ít nhất một node của mọi group.

## MN01 — Tết Âm lịch 2026

**Câu hỏi:** Đại học Cần Thơ nghỉ Tết Âm lịch 2026 từ ngày nào đến ngày nào và sinh viên
bắt đầu học lại khi nào?

**Đáp án:** Nghỉ từ 09/02/2026 đến hết 22/02/2026. Sinh viên bắt đầu học lại từ thứ Hai
23/02/2026.

**Evidence bắt buộc:** `Tet2026_doc_1_muc_1` và `Tet2026_doc_1_muc_2`.

## MN02 — Thiết bị và hỗ trợ đăng ký học phần

**Câu hỏi:** Nếu không có thiết bị cá nhân để ĐKHP trực tuyến HK1 năm học 2026-2027,
sinh viên có thể đăng ký ở đâu và được Thư viện hỗ trợ như thế nào?

**Đáp án:** Có thể dùng máy tính tại Thư viện Đại học Cần Thơ; Thư viện cử cán bộ trực và
mở cửa phòng máy theo thời gian đăng ký đã công bố.

**Evidence bắt buộc:** `KHGDVDKHP_HK1_26_27_doc_2_muc_4` và
`KHGDVDKHP_HK1_26_27_doc_2_muc_5`.

## MN03 — Nhóm đơn vị và lịch đăng ký

**Câu hỏi:** Sinh viên K50 của Trường Công nghệ Thông tin và Truyền thông hoặc Trường
Thủy sản bắt đầu ĐKHP đợt 1 HK1 năm học 2026-2027 lúc nào?

**Đáp án:** Hai trường thuộc Nhóm đơn vị 6, nên sinh viên K50 bắt đầu đăng ký lúc 13:30
ngày 05/08/2026.

**Evidence bắt buộc:** `KHGDVDKHP_HK1_26_27_doc_2_muc_1` và
`KHGDVDKHP_HK1_26_27_doc_2_muc_2_bang_1_dong_16`.

## MN04 — Lớp bị xóa và phương án xử lý

**Câu hỏi:** Lớp CT219-01 bị xóa sau đợt 1 HK1 năm học 2025-2026 là học phần nào và sinh
viên đã đăng ký lớp này có những phương án xử lý nào?

**Đáp án:** CT219-01 là học phần Xử lý ngôn ngữ tự nhiên. Sinh viên có thể chuyển kế hoạch
sang học kỳ tiếp theo, đăng ký lớp còn lại hoặc học phần thay thế trong đợt 2 từ 08/09/2025
đến 14/09/2025.

**Evidence bắt buộc:** dòng `...dong_50` trong danh sách xóa lớp và
`Xoalop_HK1_2025_2026_dot1_doc_1_muc_0`.

## MN05 — Chuyển ngành và quyền lợi

**Câu hỏi:** MSSV B2405750 được chuyển sang lớp và ngành nào, việc chuyển ngành áp dụng
từ học kỳ nào và quyền lợi sau khi chuyển được giải quyết ra sao?

**Đáp án:** Trương Khải Văn, MSSV B2405750, được chuyển sang TN2484A1, ngành Kỹ thuật
cơ khí (Chuyên ngành Cơ khí chế tạo máy), thuộc Trường Bách khoa; áp dụng từ HK2 năm học
2025-2026 và mọi chế độ, quyền lợi tiếp tục được thực hiện khi sang lớp mới.

**Evidence bắt buộc:** dòng sinh viên `...dong_20`, `...muc_điều_1` và
`...muc_điều_2` của quyết định chuyển ngành.
