Thuật toán 4. Truy xuất theo độ tương đồng ngữ nghĩa

Đầu vào: Tập thông báo trong phạm vi truy xuất, vector câu hỏi.
Đầu ra: Tập các nút phù hợp.

1. Khởi tạo tập kết quả rỗng.
2. Thực hiện truy xuất trên các nút Muc:
   - Tính độ tương đồng cosine giữa vector câu hỏi và vector của từng nút Muc.
   - Sắp xếp các nút theo độ tương đồng cosine giảm dần.
   - Lấy các nút có độ tương đồng cao nhất và thêm vào tập kết quả.
3. Thực hiện truy xuất trên các nút DongBang:
   - Tính độ tương đồng cosine giữa vector câu hỏi và vector của từng DongBang.
   - Nhóm các DongBang theo bảng chứa chúng.
   - Trong mỗi bảng, giữ lại dòng có độ tương đồng cosine cao nhất làm đại diện.
   - Sắp xếp các dòng đại diện theo độ tương đồng cosine giảm dần.
   - Lấy các dòng đại diện có độ tương đồng cao nhất và thêm vào tập kết quả.
4. Gộp kết quả truy xuất từ Muc và DongBang.
5. Sắp xếp tập kết quả theo độ tương đồng cosine.
6. Đối với các kết quả thuộc cùng một loại thông báo, ưu tiên kết quả thuộc văn bản có thời gian mới hơn.
7. Lấy top-k kết quả có thứ hạng cao nhất.
8. Trả về tập kết quả.
