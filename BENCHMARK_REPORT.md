# Benchmark & Observability Report — Day 14

> Copy file này thành `BENCHMARK_REPORT.md` trong repo của bạn và điền đầy đủ.
> Mọi con số phải lấy từ report JSON / CSV / screenshot thật, không ước lượng.

**Họ tên:** Nguyễn Thị Hồng Hạnh
**Ngày chạy:** 2026-11-25
**Môi trường:** MacBook Air Apple M1 (8 CPU, 8 GB RAM), macOS 26.6.2, Python 3.13.5; Docker 29.9.3 (Docker Desktop: 8 CPU / 4.8 GB RAM)

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Khi tải bình thường (concurrency ≤ 50) p95 đo được 220–364 ms (bảng 2.1) → còn dư ~140 ms cho tải tăng; vượt 500 ms là dấu hiệu bão hoà (concurrency 100: p95 3608.8 ms). Đặt theo p95 chứ không theo avg vì avg che giấu tail latency (bảng 2.2) |
| Error rate `/ask` | < 2 % | LLM upstream lỗi ~1% (`MOCK_ERROR_RATE=0.01`, đo được 0.33–1% ở bảng 2.1) → chừa thêm ~1% error budget cho lỗi phía agent; trùng ngưỡng mặc định của `load_test.py` |
| Accuracy trên golden dataset | ≥ 85 % | Trùng ngưỡng quality gate trong CI (`.github/workflows/eval.yml`): chặn được v1 (4.35%), cho qua v2 (91.3%) và v2 đã sửa (100%). Không đặt 100% vì chỉ cần thêm 1 câu khó vào dataset là mọi PR đều fail; regression được chặn riêng bằng `--baseline` |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.24 | 192.4 | 220.3 | 1693.6 | 1.00% | ✅ PASS |
| 10 | 38.46 | 193.4 | 363.6 | 1691.9 | 1.00% | ✅ PASS |
| 50 | 108.14 | 199.9 | 279.2 | 1712.0 | 0.33% | ✅ PASS |
| 100 | 54.62 | 601.0 | 3608.8 | 3929.8 | 0.67% | ❌ FAIL (p95) |

Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json` — mỗi mức 300 request, `MOCK_SLOW_RATE=0.03` (mặc định), SLO mặc định của `load_test.py`: p95 ≤ 500 ms, error rate ≤ 2%. Lỗi đều là `503` do mock LLM giả lập lỗi upstream (`MOCK_ERROR_RATE=0.01`).

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

- **Từ 1 → 10: gần tuyến tính** (4.24 → 38.46 req/s, ×9) và p50 gần như không đổi (~193 ms). Mỗi request chủ yếu là *chờ* mock LLM (`asyncio.sleep` ~120–180 ms), agent async nên chờ song song được → RPS ≈ concurrency / latency (10 / 0.26 s ≈ 38).
- **Từ 10 → 50: tăng nhưng không còn tuyến tính** (×2.8 thay vì ×5): 108 req/s, p50 199.9 ms vẫn ổn. Agent chạy **1 process Python, 1 event loop** — phần CPU của mỗi request (parse JSON, Pydantic, ghi log JSON, cập nhật metrics) bắt đầu thành nút thắt; tool load test cũng chạy trên cùng máy, tranh CPU.
- **Từ 50 → 100: RPS giảm** (108 → 54.6 req/s) còn p50 lên 601 ms, p95 3608.8 ms → **vượt SLO**. Agent đã bão hoà: request tới nhanh hơn khả năng xử lý nên phải **xếp hàng**; latency tăng theo hàng đợi (avg 1178 ms ≈ 100 concurrency / 54.6 RPS ≈ 1.8 s theo Little's law). Thêm concurrency khi đã bão hoà không tăng throughput mà chỉ làm latency tệ hơn.
- **p99 ~1.7 s ở mọi mức** (kể cả concurrency 1) không phải do tải mà do **tail latency giả lập**: 3% request bị cộng thêm 1500 ms (`MOCK_SLOW_RATE=0.03`) → xem 2.2.
- Kết luận: 1 instance chịu được khoảng **~50 request đồng thời (~100 req/s)** trong SLO; muốn hơn phải scale ngang (nhiều worker/instance sau load balancer — xem phần 5).

### 2.2 Tail latency

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 189.3 | 217.7 | 222.6 |
| 0.03 (mặc định) | 225.0 | 221.4 | 1690.7 |
| 0.1 | 300.0 | 1683.2 | 1715.2 |

Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json` — agent v2 bật lại với từng giá trị `MOCK_SLOW_RATE`, mỗi lần `--requests 300 --concurrency 20`. Request "slow" bị cộng thêm `MOCK_SLOW_MS=1500` ms. (p50 cả 3 lần gần như không đổi: 188.6 / 188.0 / 191.4 ms.)

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

- **p99 nhạy nhất:** chỉ cần 3% request chậm là p99 nhảy từ 222.6 → **1690.7 ms (×7.6)**, vì >1% request nằm trong nhóm chậm. Khi tỉ lệ chậm lên 10% (> 5%) thì đến lượt **p95 nhảy** từ 221.4 → **1683.2 ms**.
- **Average che giấu vấn đề:** cùng lúc đó avg chỉ tăng 189.3 → 225.0 ms (+36 ms) rồi 300.0 ms (+111 ms) — nhìn avg tưởng hệ thống vẫn ổn, trong khi thực tế 3–10% người dùng phải chờ ~1.7 s (gấp ~9 lần bình thường). Ở mức 0.03, avg (225.0) thậm chí còn **lớn hơn p95** (221.4): avg bị kéo bởi vài giá trị cực lớn nhưng không mô tả trải nghiệm của bất kỳ nhóm user nào.
- **Vì sao SLO đặt theo percentile:** SLO là cam kết về trải nghiệm người dùng ("95%/99% request nhanh hơn X ms"). Percentile trả lời trực tiếp "bao nhiêu người bị chậm và chậm tới đâu"; average trộn nhóm nhanh với nhóm chậm thành một con số không ai thực sự trải qua, và một vài request cực chậm cũng làm average dao động. Vì vậy SLO latency đặt theo **p95** (cho đa số) và theo dõi thêm **p99** (tail) — ví dụ SLO p95 < 500 ms ở bảng 1.
- Ghi chú: ở lần `MOCK_SLOW_RATE=0.03`, error rate là 2.67% (8/300 lỗi `503` ngẫu nhiên từ `MOCK_ERROR_RATE=0.01`) — dao động ngẫu nhiên của mẫu nhỏ 300 request, không liên quan tới slow rate.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.3% (21/23) | 100% (23/23) |
| Avg tokens / câu | 58.5 | 109.1 | 115.6 |
| Tổng cost (USD) | 0.000424 | 0.000762 | 0.000807 |
| Cost / câu đúng (USD) | 0.00042375 | 0.00003627 | 0.00003511 |
| Quality gate | FAIL (accuracy < 80%) | PASS (≥ 80%, 0 regression so với v1) | PASS (`--min-accuracy 1.0`, 0 regression so với v2) |

Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`. Lệnh:
```bash
python eval/run_eval.py --url http://localhost:8001 --out reports/eval_v1.json                                    # exit 1
python eval/run_eval.py --url http://localhost:8002 --out reports/eval_v2.json --baseline reports/eval_v1.json    # exit 0
python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json   # exit 0
```

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` — "JWT khác gì API key trong xác thực?" | `token`, `hết hạn`, `chữ ký` | KB không có tài liệu nào về JWT → v2 trả câu chung chung. Thêm vào cuối `KNOWLEDGE_BASE` entry `(["jwt", "api key"], "API key là chuỗi bí mật cố định, không tự hết hạn ... JWT là token có chữ ký số, chứa thông tin user (sub, role) và thời điểm hết hạn (exp) ...")` |
| `scaling-03` — "Kubernetes HPA scale dựa trên những chỉ số nào?" | `cpu`, `memory`, `custom metrics` | KB không có tài liệu về HPA. Thêm entry `(["hpa", "kubernetes", "autoscal"], "Kubernetes HPA ... tự tăng/giảm số pod dựa trên CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi.")` |

Sửa trong `develop/utils/mock_llm.py`, **không sửa** `golden_dataset.jsonl`. Thêm ở **cuối** danh sách để khi hoà điểm keyword, các entry cũ vẫn được ưu tiên → trước khi restart đã mô phỏng retrieval offline cho 23 câu: chỉ 2 câu trên đổi tài liệu được chọn. Kết quả eval cuối: 23/23, **"Câu bị regression: 0"**, "Câu được cải thiện: 2".

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Chất lượng:** retrieval (RAG) đưa accuracy từ 4.35% lên 91.3% (100% sau khi bổ sung KB). v1 chỉ biết vài câu chung chung nên gần như vô dụng.
- **Chi phí:** v2 nhét tài liệu vào prompt nên tốn **~1.9× token mỗi câu** (109.1 vs 58.5) và tổng cost cao hơn ~1.8× (0.000762 vs 0.000424 USD). Nhưng tính **cost / câu đúng** thì v2 rẻ hơn **~11.7 lần** (0.00003627 vs 0.00042375 USD) — tiền của v1 phần lớn trả cho câu trả lời sai. Vì vậy so 2 phiên bản phải dùng cost / câu đúng chứ không phải cost / câu.
- **Latency:** v2 thêm bước retrieval (~20 ms) và prompt dài hơn → p50 tăng ~45 ms (156.2 → 200.7 ms), p95 190.2 → 221.9 ms — vẫn trong SLO 500 ms. Ở lần eval cuối p95 = 1528.5 ms là do 2/23 câu (docker-01, scaling-03) trúng tail latency giả lập `MOCK_SLOW_RATE=0.03` (≈1.7 s); 23 câu là mẫu quá nhỏ nên 2 request chậm (~9%) đủ đẩy p95 lên — không phải do thay đổi KB (latency đo SLO phải dựa trên load test nhiều request, mục 2).
- **Bổ sung KB** chỉ tăng avg tokens 109.1 → 115.6 (+6%) nhưng sửa được 2 câu → cost / câu đúng còn giảm nhẹ (0.00003627 → 0.00003511 USD).
- Kết luận: chọn **v2** — đắt hơn mỗi request nhưng rẻ hơn nhiều trên mỗi câu trả lời có giá trị, latency tăng nhẹ vẫn trong SLO.

**Quality gate trong CI** — file [`.github/workflows/eval.yml`](.github/workflows/eval.yml), chạy cho mỗi Pull Request sửa `06-lab-complete/benchmark-observability/develop/**`:
1. Checkout, cài Python 3.11 + `requirements.txt`.
2. Bật agent v2 nền (`MOCK_ERROR_RATE=0` để lỗi upstream ngẫu nhiên không làm CI fail oan), chờ `/health` 200.
3. `python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85 --baseline reports/eval_v2_fixed.json`

`run_eval.py` trả **exit code 1** khi accuracy < 85% **hoặc** có câu bị regression so với baseline đã duyệt (câu trước đúng, giờ sai). Exit code ≠ 0 → step fail → job `quality-gate` fail → PR hiện ❌; bật branch protection "Require status checks to pass" cho `main` thì PR **không merge được** tới khi sửa xong. Chạy thử các bước của job trên máy: `Accuracy 100.0% (23/23)`, `Câu bị regression: 0`, `Quality gate (accuracy ≥ 85%, không regression): ✅ PASS`. Ngược lại agent v1 (4.35%) cho exit code 1 (lệnh eval v1 ở trên).

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

...

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. ...
  2. ...
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...
