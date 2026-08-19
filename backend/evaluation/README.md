# Benchmark miền Thông báo

Bộ benchmark dùng 35 case cố định trong `notification_qa_30.json` (giữ tên file để tương
thích với các lệnh cũ). Script gọi trực tiếp
`ThongBaoPipeline.run()` rồi dùng `LLMService.generate()` giống nhánh `THONG_BAO` của
`ChatOrchestrator`; không gọi HTTP và không đọc log terminal.

Ba mươi case đơn node có đúng một tập `gold_evidence_any_of`. Nếu cùng một fact đầy đủ xuất
hiện ở nhiều node tương đương, chỉ cần một node trong tập xuất hiện là evidence hợp lệ. Năm
case `Multi-node` dùng `evidence_groups`: phải phủ đủ mọi group (`ALL_GROUPS`), còn các node
trong từng group là tương đương (`ANY_OF`). `required_facts` vẫn dùng riêng để người đánh
giá chấm Answer Accuracy.

## Chuẩn bị

- Chạy Neo4j với đúng KG snapshot của bộ ground truth.
- Chạy Ollama và model được cấu hình trong `.env`.
- Kích hoạt môi trường Python đã cài `backend/requirements.txt`.
- `CHAT_GLOBAL_TOP_K` phải giống cấu hình thực nghiệm; hiện tại là `6`.

Các lệnh dưới đây chạy từ thư mục `backend`.

## Chạy benchmark

Chạy đủ 35 câu tuần tự, để trống Answer Accuracy:

```powershell
python scripts/evaluate_notifications.py
```

Chạy một case và chấm answer ngay:

```powershell
python scripts/evaluate_notifications.py --case T01 --grade-answers
```

Chạy một số case để smoke test:

```powershell
python scripts/evaluate_notifications.py --limit 3
```

Script mặc định resume: ID đã có trong CSV sẽ được bỏ qua. Muốn chạy lại phần đã chọn:

```powershell
python scripts/evaluate_notifications.py --case T01 --no-resume
```

Chấm thủ công các answer đã lưu mà không gọi lại pipeline/model:

```powershell
python scripts/evaluate_notifications.py --grade-only
```

Dùng thêm `--regrade` nếu muốn chấm lại cả những hàng đã có 0/1.

## Metric

Với chính `K` được truyền vào `ThongBaoPipeline.run(top_k=K)`:

- **Direct Evidence Hit@K** = 1 khi `selected_candidates[:K]` phủ đủ mọi evidence group.
  Với case đơn node, tập `gold_evidence_any_of` được xem là một group duy nhất.
- **Final Evidence Hit** = 1 khi bundle `selected_candidates + expanded_candidates` phủ đủ
  mọi evidence group.
- **Recovered by Expansion** = 1 chỉ khi Direct Hit@K = 0 và Final Evidence Hit = 1.
- **Expansion Recovery Rate** = số case recovered chia cho số case Direct Hit@K = 0.
  Nếu không có Direct miss, kết quả là N/A.
- **Answer Accuracy** do người dùng nhập: 1 khi answer đủ mọi `required_facts`, ngược lại 0.

Direct Hit@K = 1 nhưng Final Evidence Hit = 0 là trạng thái bất khả thi vì final bundle luôn
chứa selected candidates; evaluator sẽ dừng và báo invariant error nếu gặp trạng thái này.

## Checkpoint, CSV và migration

Mỗi case độc lập, không có conversation history và toàn bộ case chạy tuần tự. CSV mới mặc định:

```text
evaluation/notification_results_evidence.csv
```

CSV được ghi atomically sau từng câu. Các cột metric chính là `top_k`, `topk_ids`,
`direct_hit_at_k`, `final_evidence_hit` và `recovered_by_expansion`.

File cũ `evaluation/notification_results.csv` dùng Hit@5/Expansion Complete được giữ nguyên
nhưng không được resume như kết quả của metric mới. Nếu truyền một CSV schema cũ qua
`--output`, evaluator sẽ từ chối và yêu cầu dùng output mới. Tương tự, một CSV không được
trộn các lần chạy với giá trị K khác nhau.

Benchmark cuối phải chạy lại đủ 35 câu với cùng KG snapshot và K thực tế.

## Trạng thái audit

Cột `error` nhận các trạng thái chính:

- `UNGRADED`: Answer Accuracy chưa được chấm.
- `OK`: answer đúng và final bundle có explicit gold evidence.
- `GOLD_AUDIT`: answer đúng nhưng final bundle không có explicit gold evidence.
- `EVIDENCE_MISS`: answer sai và final bundle thiếu gold evidence.
- `GENERATION`: final bundle có gold evidence nhưng answer sai.
- `RUNTIME_*`: lỗi khi chạy pipeline hoặc generation.

`GOLD_AUDIT` chỉ yêu cầu kiểm tra thủ công, không tự kết luận ground truth sai.
