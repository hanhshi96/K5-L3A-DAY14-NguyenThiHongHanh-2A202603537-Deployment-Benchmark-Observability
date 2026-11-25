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

Stack chạy bằng `docker compose -p k5-day14-observability up -d --build` trong `06-lab-complete/benchmark-observability/production/` (2 agent v2 + Nginx + Prometheus + Grafana + Jaeger + Locust). Tải: Locust headless 30 user, ramp 5/s, bắt đầu 16:49:41.

*Sự cố khi bật stack:* 2 container agent restart liên tục với `ModuleNotFoundError: No module named 'uvicorn'`. Nguyên nhân: `production/Dockerfile` tạo user bằng `useradd -d /app` → `HOME=/app` nên Python tìm thư viện `--user` ở `/app/.local`, trong khi thư viện được copy vào `/home/agent/.local`. Sửa: thêm `ENV PYTHONUSERBASE=/home/agent/.local` → agent healthy, `/ask` 200 qua Nginx.

### 4.0 Trả lời Exercise 7.4 (đọc từ dashboard khi có tải)

Ảnh: `screenshots/grafana-dashboard.png` (Golden Signals), `grafana-dashboard-2.png` (latency tooltip lúc 16:59:25, tokens/s, cost), `grafana-dashboard-3.png` (req/s theo instance, version).

**1. p95 và avg là bao nhiêu? Khoảng cách nói lên điều gì?**
Panel Golden Signals: p95 = **295.70 ms**. Tooltip đồ thị latency lúc 16:59:25: **p50 180 ms · avg 236 ms · p95 294 ms · p99 1.83 s**. avg (236 ms) chỉ cao hơn p50 ~56 ms và thấp hơn p95, nhưng p99 lên tới 1.83 s (vượt vạch đỏ 1 s). Khoảng cách avg ↔ p99 rất lớn trong khi avg ↔ p95 nhỏ nghĩa là phân bố latency có **đuôi dài**: đa số (> 95%) request nhanh ~180–300 ms, còn một nhóm nhỏ (~3%, `MOCK_SLOW_RATE=0.03`) chậm ~1.7–1.8 s. avg bị nhóm chậm kéo lên một chút nên nằm giữa p50 và p95, nhưng không cho thấy có user phải chờ ~2 s → phải nhìn p95/p99 (khớp kết quả load test mục 2.2).

**2. Panel "Requests/s theo instance": Nginx có chia đều traffic không?**
Có. 2 đường `172.18.0.6:8000` và `172.18.0.7:8000` gần như trùng nhau, mỗi instance ~9–10 req/s, tổng ≈ Traffic 18.4 req/s ở Golden Signals. Nginx `upstream agent_cluster { server agent:8000 resolve; }` lấy IP của cả 2 replica từ Docker DNS và chia round-robin; header `X-Served-By` khi curl cũng luân phiên `172.18.0.7` ↔ `172.18.0.6`. Bảng "Phiên bản đang chạy": `mock-llm-small`, `v2`, 2 instance.

**3. Vì sao input tokens/s lớn hơn output tokens/s?**
Panel Tokens/s là đồ thị **xếp chồng** (stacking `normal`): phần xanh (input) ~1.4K tokens/s, đường vàng (output) được cộng lên trên tới ~2.2K → output ≈ 0.75K tokens/s; input ≈ **2 lần** output. Vì agent v2 làm RAG: prompt = system prompt + **tài liệu retrieve được** (retrieval hit ratio 100%) + câu hỏi, còn câu trả lời ngắn (mock trả đúng 1 đoạn tài liệu). Mỗi request input gồm cả context lẫn câu hỏi nên luôn dài hơn output. (Giá output đắt hơn input 4 lần nên cost vẫn chịu ảnh hưởng lớn từ output.)

**4. `curl http://localhost:8080/metrics` trả về gì? Vì sao?**
```text
$ curl -i http://localhost:8080/metrics
HTTP/1.1 404 Not Found
```
Nginx chặn: `location = /metrics { return 404; }`. `/metrics` lộ thông tin nội bộ (số request, lỗi, cost, version, tên model) và nếu public thì ai cũng scrape được, thậm chí spam làm tốn tài nguyên. Prometheus không đi qua Nginx mà scrape thẳng từng agent trong network nội bộ (`dns_sd_configs` → `agent:8000/metrics`), nên chặn ở Nginx không ảnh hưởng monitoring. (Tương tự, `/ask` không có `X-API-Key` → 401.)

**Phát hiện thêm — alert cost firing ở tải bình thường:** panel "Cost burn rate" ~$2.37/giờ, vượt ngưỡng $2 của `LLMCostBurnRateHigh`. Prometheus: alert vào **pending lúc 16:53:57** (~4 phút 16 giây sau khi Locust bắt đầu — cửa sổ `rate(...[5m])` đầy dần dữ liệu) rồi **firing ~2 phút sau** (`for: 2m`), dù chỉ có 30 user dùng model nhỏ và không có sự cố. Ngưỡng $2/giờ quá thấp so với tải bình thường này → alert dễ thành báo động giả, cần đặt theo budget thực tế (vd theo `DAILY_BUDGET_USD`) hoặc theo mức tăng bất thường so với baseline.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals) — `screenshots/grafana-dashboard.png`, `grafana-dashboard-2.png`, `grafana-dashboard-3.png`
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian) — `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger (có event `exception`) — `screenshots/jaeger-error-trace.png`
- [x] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing** — `screenshots/prometheus-alert-firing.png`: nhóm `agent-slo` **FIRING (2)** — `AgentHighErrorRate` (value 0.2119, active 2m 46.978s) và `AgentHighLatencyP95` (value 1.8858, active 3m 19.825s)

### 4.2 Thí nghiệm "phá hệ thống"

Unit test alert rules trước khi làm thí nghiệm:
```text
$ docker run --rm -v "$PWD/prometheus:/p" --entrypoint promtool prom/prometheus:v3.16.0 test rules /p/alert_rules_test.yml
Processing test file: /p/alert_rules_test.yml
  SUCCESS
```

Cách làm: Locust 30 user chạy liên tục (bắt đầu 17:12:32). Làm **A và B cùng lúc**: tạo `production/.env` với `MOCK_ERROR_RATE=0.2`, `MOCK_SLOW_RATE=0.3`, chạy `docker compose -p k5-day14-observability up -d agent` lúc **17:12:51** (T0). Một script hỏi `GET /api/v1/alerts` của Prometheus mỗi 5 giây và ghi lại lúc trạng thái đổi (sai số ±5 s):

```text
17:12:51 bắt đầu theo dõi
17:12:51 LLMCostBurnRateHigh: firing  (activeAt UTC 2026-11-25T09:53:57)
17:13:06 AgentInstanceDown: pending  (activeAt UTC 2026-11-25T10:12:57)
17:13:11 AgentInstanceDown: inactive
17:13:21 AgentHighLatencyP95: pending  (activeAt UTC 2026-11-25T10:13:12)
17:13:26 AgentHighErrorRate: pending  (activeAt UTC 2026-11-25T10:13:17)
17:14:26 AgentHighErrorRate: firing  (activeAt UTC 2026-11-25T10:13:17)
17:14:51 LLMCostBurnRateHigh: inactive
17:15:21 AgentHighLatencyP95: firing  (activeAt UTC 2026-11-25T10:13:12)
17:15:21 ✅ cả 2 alert đều firing
```
Trả cấu hình (xoá `.env`, `up -d agent`) lúc 17:17:13 → cả 2 alert hết (resolved) lúc 17:18:14 (~61 s).

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (critical) — value khi chụp 0.2119 (> 0.05) | **~1 phút 35 giây** (17:12:51 → firing 17:14:26; pending từ 17:13:17, +26 s) | Golden Signals "Error rate" chuyển đỏ (~20%); "LLM calls theo kết quả" (đường `error` tăng); Jaeger có nhiều trace `error=true` |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (warning) — value khi chụp 1.8858 s (> 1 s) | **~2 phút 30 giây** (17:12:51 → firing 17:15:21; pending từ 17:13:12, +21 s) | "Latency /ask — p50/p95/p99": p95 nhảy lên ~1.9 s (cùng mức p99) trong khi p50 gần như không đổi; "LLM latency p95 theo model" |
| C | `LLM_MODEL=mock-llm-large` | Không làm riêng. `LLMCostBurnRateHigh` **đã firing ngay ở tải bình thường** với `mock-llm-small` (pending 16:53:57, ~4 phút sau khi có tải; burn rate ~$2.37/giờ > $2) nên không đo được "thời gian từ lúc đổi" | — | "Cost burn rate (USD/giờ)" vượt vạch đỏ $2 (ảnh `grafana-dashboard-2.png`) |
| D | `docker pause` 1 instance | Không làm | — | — |
| E | `AGENT_VERSION=v1` | Không làm (theo README: không alert nào) | — | — |

**Phân tích:**
- **Thời gian tới firing ≈ thời gian để biểu thức vượt ngưỡng + `for`.** Biểu thức dùng `rate(...[1m])` nên phải ~20–25 s dữ liệu xấu mới đủ kéo tỉ lệ lỗi > 5% / p95 > 1 s (pending lúc +26 s và +21 s); sau đó chờ thêm `for: 1m` (A) hoặc `for: 2m` (B). Alert latency để `for` dài hơn vì latency dao động nhiều hơn, tránh báo động giả từ một đợt chậm ngắn; alert error là `critical` nên phản ứng nhanh hơn.
- **`for` chặn được báo động giả:** khi recreate container, `AgentInstanceDown` vào pending 5 giây (Prometheus còn scrape IP của container cũ vừa bị xoá) rồi tự hết — nhờ `for: 30s` nên không bao giờ firing.
- **Một chỉ số không đủ:** khi hệ thống tệ đi (20% lỗi + 30% chậm), `LLMCostBurnRateHigh` lại **tự tắt** lúc 17:14:51 — call lỗi không tính tiền và request chậm làm giảm throughput, nên tốc độ tiêu tiền tụt dưới $2/giờ. Nhìn riêng cost sẽ tưởng mọi thứ ổn hơn.
- **Ngưỡng cost cần chỉnh:** `LLMCostBurnRateHigh` firing ở tải bình thường (30 user, model nhỏ) là báo động giả — người trực sẽ quen bỏ qua alert. Nên đặt theo budget thực tế, hoặc theo mức tăng so với baseline (vd burn rate > 2× trung bình 1 ngày).
- **Resolve:** sau khi trả cấu hình, cả 2 alert hết sau ~61 s (cửa sổ `rate` 1 phút đã sạch dữ liệu xấu).

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Đổi sang v1 làm **chất lượng** giảm (accuracy 100% → 4.35% ở mục 3) nhưng latency, error rate, instance đều bình thường — metric hạ tầng chỉ biết request "thành công và nhanh", không biết câu trả lời đúng hay sai. Cách phát hiện:
1. **Chặn trước khi deploy:** quality gate trong CI (`.github/workflows/eval.yml`) chạy golden dataset, v1 có exit code 1 → PR không merge được.
2. **Eval liên tục trên production:** job định kỳ (vd mỗi 15 phút) gửi golden dataset vào agent đang chạy, đẩy accuracy thành metric (vd `agent_eval_accuracy`) và đặt alert `agent_eval_accuracy < 0.85`.
3. **Proxy metric chất lượng:** theo dõi *Retrieval hit ratio* (rơi từ 100% về 0 khi đổi sang v1) và tokens/s (giảm vì prompt không còn context) — alert khi hit ratio giảm đột ngột. Bảng "Phiên bản đang chạy" cho thấy version đã đổi.
4. **Tín hiệu từ người dùng:** tỉ lệ 👍/👎, câu hỏi lặp lại, tỉ lệ chuyển sang người hỗ trợ.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

Ảnh: `screenshots/jaeger-slow-trace.png` (tìm bằng "Lookup by Trace ID", trace chậm ~1.7–1.8 s khi sắp xếp Longest First).

- `trace_id`: `5f94011eedffae2352c44b98425e5a85` (bắt đầu 16:57:08.095, agent v2, `mock-llm-small`)
- Tổng thời gian: **1754.1 ms** (Jaeger hiển thị "Duration 1.8s", 4 span, depth 3)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**1723.4 ms, ~98%** tổng thời gian; Jaeger hiển thị "Duration 1.7s", tokens input 81 / output 46)

  ```text
  POST /ask                    1754.1 ms
  └── agent.run                1744.2 ms
      ├── agent.retrieve_context  19.4 ms   (~1%)
      └── chat mock-llm-small   1723.4 ms   (~98%)  ← LLM upstream chậm (tail latency giả lập)
  ```
  → Request chậm do **LLM provider**, không phải code agent hay retrieval (19.4 ms). Cách xử lý đúng: timeout + retry/fallback model, streaming để user thấy chữ sớm, cache câu hỏi lặp lại — tối ưu code agent không giúp được.
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep 5f94011eedffae2352c44b98425e5a85`):

```json
{"ts": "2026-11-25T09:57:09.841854+00:00", "level": "INFO", "service": "observable-agent", "instance": "9ecf680cd4aa", "event": "llm_call", "trace_id": "5f94011eedffae2352c44b98425e5a85", "span_id": "cf52f29fd945d8b1", "request_id": "a1af0b80ec71", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 81, "output_tokens": 46, "cost_usd": 4e-05, "llm_ms": 1683.3}
{"ts": "2026-11-25T09:57:09.849063+00:00", "level": "INFO", "service": "observable-agent", "instance": "9ecf680cd4aa", "event": "http_request", "trace_id": "5f94011eedffae2352c44b98425e5a85", "span_id": "cf52f29fd945d8b1", "request_id": "a1af0b80ec71", "method": "POST", "route": "/ask", "status": 200, "ms": 1753.0}
```
(`ts` trong log là UTC: 09:57:09 UTC = 16:57:09 giờ VN, khớp Trace Start 16:57:08 + 1.75 s.)

**Trace lỗi** — `screenshots/jaeger-error-trace.png`:
- `trace_id`: `1ec8a55f602bb1719b52014f7ba41dc8` (bắt đầu 17:03:07.084), tổng **121 ms**, `POST /ask` trả **503**.
- Span `chat mock-llm-small` (**89.3 ms**) và `agent.run` có status ERROR + event **`exception`**: `utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`. Lỗi trả về nhanh hơn request thành công (~120 ms so với ~200 ms) — upstream từ chối sớm.
- Log tương ứng:

```json
{"ts": "2026-11-25T10:03:07.204019+00:00", "level": "INFO", "service": "observable-agent", "instance": "4527f8331175", "event": "llm_error", "trace_id": "1ec8a55f602bb1719b52014f7ba41dc8", "span_id": "659d2a58aeac0681", "request_id": "cfc6e0443bee", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-25T10:03:07.204698+00:00", "level": "INFO", "service": "observable-agent", "instance": "4527f8331175", "event": "http_request", "trace_id": "1ec8a55f602bb1719b52014f7ba41dc8", "span_id": "659d2a58aeac0681", "request_id": "cfc6e0443bee", "method": "POST", "route": "/ask", "status": 503, "ms": 120.0}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 65.94 | 190 | 250 | 1700 | 60 / 7875 (0.76%) |
| 3 | 65.68 | 190 | 240 | 1700 | 71 / 7845 (0.90%) |

Nguồn: `benchmark-results/scale_1_stats.csv`, `benchmark-results/scale_3_stats.csv` (dòng `Aggregated`; riêng `POST /ask`: scale 1 → 59.52 req/s, p50 200 / p95 250 / p99 1700 ms, 60 lỗi / 7109; scale 3 → 59.84 req/s, p50 200 / p95 250 / p99 1700 ms, 71 lỗi / 7148). Lệnh:
```bash
docker compose -p k5-day14-observability up -d --scale agent=1
docker compose -p k5-day14-observability run --rm locust -f /mnt/locust/locustfile.py --host http://nginx \
  --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_1
docker compose -p k5-day14-observability up -d --scale agent=3
docker compose -p k5-day14-observability run --rm locust -f /mnt/locust/locustfile.py --host http://nginx \
  --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_3
```
Trước mỗi lần chạy đã chờ Prometheus thấy đúng 1 / 3 target agent `up`. Toàn bộ lỗi là `503` từ mock LLM (`MOCK_ERROR_RATE=0.01`, file `scale_*_failures.csv`).

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

- **Không cải thiện:** RPS (65.94 → 65.68), p50 (190 → 190 ms), p95 (250 → 240 ms) và p99 (1700 → 1700 ms) gần như y hệt; chênh lệch nằm trong dao động ngẫu nhiên.
- **Vì sao RPS không tăng:** Locust là tải "đóng" — 100 user, mỗi user gửi 1 request rồi nghỉ `between(0.5, 2)` giây. Lượng request tối đa họ tạo ra ≈ 100 / (1.25 s nghỉ trung bình + ~0.22 s chờ) ≈ **68 req/s**, đúng bằng con số đo được. Ngay cả 1 instance (0.5 CPU) đã phục vụ kịp lượng tải này — agent không bão hoà, nên thêm instance không có request nào để xử lý thêm. Throughput bị giới hạn bởi **phía người dùng**, không phải phía server.
- **Vì sao p95/p99 không giảm:** latency gần như hoàn toàn là thời gian **chờ LLM** — p50 ~200 ms ≈ `MOCK_LATENCY_MS=120` + jitter + token; p99 = 1700 ms chính là 3% request bị cộng 1500 ms (`MOCK_SLOW_RATE=0.03`). Trace ở mục 4.3 cũng cho thấy span `chat mock-llm-*` chiếm ~98% thời gian. Thêm instance agent **không làm LLM provider nhanh hơn** → nút thắt nằm ở **LLM upstream**.
- **Khi nào scale mới có ích:** khi agent là nút thắt — vd load test develop ở mục 2.1 với concurrency 100 không nghỉ, 1 process Python bão hoà (RPS giảm còn 54.62, p95 3608.8 ms). Lúc đó thêm instance sau load balancer sẽ tăng throughput. Còn với latency do LLM, cần cách khác: model nhanh hơn, cache câu trả lời, streaming, timeout + fallback cho request chậm.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Average nói dối, percentile mới nói thật.** Chỉ 3% request chậm đã đẩy p99 từ 222.6 lên 1690.7 ms trong khi avg chỉ tăng 36 ms (mục 2.2) — SLO phải đặt theo p95/p99. Và mọi con số phải đi kèm file dữ liệu gốc (JSON/CSV) mới kiểm chứng được.
  2. **Metric hạ tầng không đo được chất lượng.** Dashboard toàn xanh vẫn có thể đang trả lời sai (thí nghiệm E, v1 chỉ đúng 4.35%). Cần eval trên golden dataset làm quality gate trong CI và so sánh bằng *cost / câu đúng* chứ không phải *cost / câu* (v2 đắt gấp ~1.8 lần mỗi câu nhưng rẻ hơn ~11.7 lần mỗi câu đúng).
  3. **Metrics → traces → logs nối với nhau bằng `trace_id`.** Metric cho biết *có vấn đề* (p99 cao), trace chỉ ra *ở đâu* (span `chat mock-llm-small` chiếm ~98%), log cho *chi tiết* (token, lỗi). Nhờ vậy biết được scale agent không giúp gì khi nút thắt là LLM (mục 5). Ngoài ra alert cũng cần được test (`promtool`) và chỉnh ngưỡng — `LLMCostBurnRateHigh` báo động giả ở tải bình thường, còn `for` giúp tránh báo động giả khi container restart.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

  - **Chất lượng:** chạy eval định kỳ trên production, xuất `agent_eval_accuracy` và alert khi < 85%; alert khi *retrieval hit ratio* giảm đột ngột; thu thập 👍/👎 của người dùng thành metric.
  - **Tầng load balancer / bên ngoài:** metric và alert 5xx/504 ở Nginx (lỗi do agent treo không hiện trong metric của agent) và synthetic check gọi `/ask` từ bên ngoài mỗi phút.
  - **Cost:** alert theo budget thật (% `DAILY_BUDGET_USD` đã dùng, vd > 80%) và theo mức tăng bất thường so với baseline thay vì ngưỡng cố định $2/giờ; cost theo model/version.
  - **Bảo vệ:** số request bị 429 (rate limit) và 402 (hết budget) theo thời gian; tỉ lệ 401 tăng đột biến (dò key).
  - **Saturation:** CPU/memory từng container, độ dài hàng đợi / in-flight vượt ngưỡng → tín hiệu để autoscale trước khi p95 vỡ SLO.
  - **Burn-rate alert cho SLO** (multi-window: 1h + 5m) thay cho ngưỡng tức thời, để alert theo mức tiêu error budget.
