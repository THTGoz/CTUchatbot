Thuật toán 3. Truy xuất chính xác trên dữ liệu bảng

Đầu vào: Tập thông báo trong phạm vi truy xuất, các giá trị định danh trong câu hỏi (MSSV, mã học phần, khóa), vector câu hỏi.

Đầu ra: Tập các dòng bảng phù hợp.

1. Khởi tạo tập kết quả rỗng.
2. Duyệt từng bảng thuộc các thông báo trong phạm vi truy xuất.
3. Với mỗi bảng:
   - Kiểm tra tiêu đề các cột để xác định cột chứa MSSV, mã học phần hoặc khóa.
   - Chỉ sử dụng những cột tương ứng với các giá trị định danh xuất hiện trong câu hỏi.
   - Nếu bảng không có cột phù hợp với câu hỏi, bỏ qua bảng này.
4. Duyệt các dòng của bảng:
   - So sánh giá trị trong các cột đã xác định với giá trị được trích xuất từ câu hỏi.
   - Nếu dòng thỏa các giá trị cần đối chiếu, tính độ tương đồng cosine giữa dòng và câu hỏi.
   - Lưu dòng cùng độ tương đồng cosine vào tập kết quả.
5. Nếu một bảng có nhiều dòng phù hợp, chỉ giữ lại dòng có độ tương đồng cosine cao nhất làm đại diện cho bảng.
6. Sắp xếp các dòng đại diện theo độ tương đồng cosine giảm dần.
7. Trả về tập kết quả.
