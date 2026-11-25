# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được lấy trực tiếp từ các file JSON trong `reports/`, CSV trong `benchmark-results/` và screenshot thực tế trong `screenshots/`.

**Họ tên:** Ngô Đức Thịnh (MSSV: 2A202603548)  
**Ngày chạy:** 2026-11-25  
**Môi trường:** Windows 11 + WSL2 Ubuntu (Python 3.12.3, `posix`), Docker Desktop 28.0.1 / Docker Compose v2.33.1

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | ≤ 500 ms | 95% người dùng nhận phản hồi dưới 0.5 giây, đủ mượt cho trải nghiệm chat realtime (khớp mặc định `--slo-p95-ms 500` trong `load_test.py`). |
| Error rate `/ask` | ≤ 2.0 % | Cho phép sai số nhỏ từ lỗi upstream ngẫu nhiên (`MOCK_ERROR_RATE=0.01`), đảm bảo độ tin cậy ≥ 98% (khớp mặc định `--slo-error-rate 0.02`). |
| Accuracy trên golden dataset | ≥ 100 % (không regression) | Đảm bảo toàn bộ 23 câu hỏi kiến thức cốt lõi đều được agent v2 trả lời chính xác trước khi merge/deploy lên production. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 requests/mức)

Nguồn dữ liệu: `reports/load_v2_c1.json`, `reports/load_v2_c10.json`, `reports/load_v2_c50.json`, `reports/load_v2_c100.json`.

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.89 | 189.5 | 219.9 | 1703.7 | 1.33% (4/300) | PASS |
| 10 | 40.61 | 189.1 | 218.6 | 1670.3 | 1.00% (3/300) | PASS |
| 50 | 107.16 | 192.0 | 284.8 | 1701.9 | 1.33% (4/300) | PASS |
| 100 | 130.49 | 210.1 | 434.9 | 1724.5 | 1.33% (4/300) | PASS |

**Nhận xét:** RPS **không tăng tuyến tính** theo concurrency ở mức tải cao:
- Từ `c=1 → c=10` (tăng 10×), RPS tăng gần tuyến tính từ `3.89 → 40.61` (~10.4×) vì app chạy `async` (`await asyncio.sleep(...)`) nên trong lúc chờ I/O mock LLM, event loop phục vụ được đồng thời nhiều request mà p50/p95 hầu như không đổi (~189 ms / ~219 ms).
- Từ `c=10 → c=50` (5×), RPS chỉ tăng ~2.6× (`40.61 → 107.16`) và p95 tăng lên `284.8 ms`.
- Từ `c=50 → c=100` (2×), RPS chỉ tăng ~1.22× (`107.16 → 130.49`) trong khi p95 vọt lên `434.9 ms` (tiệm cận ngưỡng SLO 500 ms). Nguyên nhân là **single process event loop** bắt đầu bão hòa ở phần JSON serialization, logging, middleware metrics và TCP/HTTP handling khi 100 request dồn đồng thời, tạo ra hàng đợi (queuing delay).

### 2.2 Tail latency (`--requests 300 --concurrency 20`)

Nguồn dữ liệu: `reports/load_v2_slow_0.json`, `reports/load_v2_slow_0.03.json`, `reports/load_v2_slow_0.1.json`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) | SLO p95 ≤ 500ms |
|---|---|---|---|---|
| 0 | 193.5 | 220.6 | 319.5 | PASS |
| 0.03 (mặc định) | 229.9 | 221.4 | 1690.5 | PASS |
| 0.1 | 326.4 | 1676.5 | 1705.8 | FAIL |

**Nhận xét:**
- **Chỉ số nhạy nhất với request chậm là `p99` và `p95` (tail latency):**
  - Khi `MOCK_SLOW_RATE` tăng từ `0 → 0.03` (chỉ 3% request chậm thêm 1.5s), `avg` chỉ nhích nhẹ từ `193.5 → 229.9 ms` (+18.8%) nhưng `p99` nhảy vọt hơn **5 lần** (`319.5 → 1690.5 ms`).
  - Khi `MOCK_SLOW_RATE = 0.1` (10% request chậm), `avg` vẫn chỉ là `326.4 ms` (trông có vẻ rất đẹp, dưới 500 ms), nhưng cả `p95` (`1676.5 ms`) lẫn `p99` (`1705.8 ms`) đều vượt xa ngưỡng 500 ms → **FAIL SLO**.
- **Vì sao SLO không nên đặt theo average?** Giá trị trung bình bị làm loãng bởi 90–97% request nhanh nên **che giấu trải nghiệm tệ của nhóm người dùng ở đuôi phân phối** (tail latency). Trong thực tế, 1 trang web hoặc agent gọi nhiều bước nối tiếp nhau khiến xác suất người dùng dính ít nhất 1 request chậm tăng rất nhanh, nên SLO bắt buộc đặt theo `p95` hoặc `p99`.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Nguồn dữ liệu: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.

| Chỉ số | Agent v1 | Agent v2 (ban đầu) | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Latency p50 / p95 (ms) | 164.7 / 190.0 | 181.0 / 222.2 | 193.7 / 221.8 |
| Avg tokens / câu | 57.7 | 108.8 | 114.2 |
| Tổng cost (USD) | $0.000412 | $0.000758 | $0.000795 |
| Cost / câu đúng (USD) | $0.00041235 | $0.00003607 | $0.00003458 |
| Quality gate | FAIL (< 80%) | PASS (≥ 80%, 0 regression) | PASS (≥ 100%, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách sửa** (sửa `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` và đồng bộ sang `production/utils/mock_llm.py`, không sửa `golden_dataset.jsonl`):

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm mục kiến thức cho từ khóa `["jwt", "json web token"]` giải thích JWT tự chứa thông tin user kèm chữ ký số, có thời gian hết hạn (`exp`) và xác thực stateless, đối chiếu với API key tĩnh. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm mục kiến thức cho từ khóa `["kubernetes", "hpa"]` mô tả Kubernetes HPA tự động scale replica dựa trên CPU, memory và các custom metrics (như RPS, độ dài hàng đợi). |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- **Chất lượng:** v2 (có bước retrieval RAG từ `KNOWLEDGE_BASE`) tăng vọt accuracy từ `4.3% (1/23)` lên `91.3% (21/23)` và đạt `100.0% (23/23)` sau khi bổ sung KB, không gây regression câu nào.
- **Latency:** v2 chậm hơn v1 khoảng `~32 ms` ở p95 (`190.0 → 221.8 ms`) do tốn thêm bước `search_knowledge_base` (~20 ms) và prompt dài hơn.
- **Chi phí:** Tổng cost trên 23 câu của v2 (`$0.000795`) gần gấp đôi v1 (`$0.000412`) vì prompt có thêm context retrieval làm `avg_tokens` tăng từ `57.7 → 114.2`. Tuy nhiên xét theo chỉ số hiệu quả thật là **cost / câu trả lời đúng**, v2 (`$0.00003458`) lại **rẻ hơn gần 12 lần** so với v1 (`$0.00041235`), vì v1 tốn tiền sinh ra 22/23 câu trả lời vô ích.

**Cách dùng exit code của `run_eval.py` làm Quality Gate trong CI/CD (chặn merge):**
- `eval/run_eval.py` kết thúc với `SystemExit(0)` khi `accuracy >= --min-accuracy` **và** không có câu nào bị regression so với `--baseline`; ngược lại trả **`exit code 1`**.
- Khi tích hợp vào GitHub Actions (ví dụ `.github/workflows/eval-gate.yml`), bước chạy `run_eval.py` thất bại (`exit code 1`) sẽ làm job CI báo đỏ và bật **Branch Protection (Require status checks to pass)** để tự động chặn merge PR có regression:

```yaml
name: Agent Quality Gate
on: [pull_request]
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r 06-lab-complete/benchmark-observability/develop/requirements.txt
      - name: Start agent v2 and run eval quality gate
        working-directory: 06-lab-complete/benchmark-observability/develop
        run: |
          AGENT_VERSION=v2 PORT=8002 python app.py &
          sleep 2
          python eval/run_eval.py \
            --url http://localhost:8002 \
            --min-accuracy 1.0 \
            --baseline ../../../../reports/eval_v2.json
```

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (`screenshots/grafana-dashboard.png`) — thấy rõ 4 Golden Signals, Latency & Traffic, LLM metrics và phân bố Instances.
- [x] Một trace chậm trong Jaeger (`screenshots/jaeger-slow-trace.png`) — `trace_id = 1a4c41c97b41f50046343598987052f7`, span `chat mock-llm-small` chiếm 1671.95 ms (98.5%).
- [x] Một trace lỗi trong Jaeger (`screenshots/jaeger-error-trace.png`) — `trace_id = 7ad2b8875602fcbd91d949b30c1acfb2`, có event `exception` (`Upstream LLM error: 503 Service Unavailable (mock)`).
- [x] Trang Alerts của Prometheus với **4 alert đồng loạt firing** (`screenshots/prometheus-alert-firing.png`).

### Trả lời câu hỏi Exercise 7.4 (quan sát Grafana & Prometheus dưới tải 3 instance)

1. **p95 và avg đang là bao nhiêu? Khoảng cách giữa chúng nói lên điều gì?**
   - Dưới tải Locust (`scale=3`, `MOCK_SLOW_RATE=0.03`), Prometheus ghi nhận `p95 ≈ 296 ms` (`0.2957 s`) và `avg ≈ 240 ms` (`0.2396 s`), trong khi `p99 ≈ 1700 ms`. Khoảng cách lớn giữa `avg`/`p50` (~190–240 ms) và `p99` (~1700 ms) phản ánh **tail latency** (~3% request bị chậm bất thường +1500 ms).
2. **Panel "Requests/s theo instance": Nginx có chia đều traffic không?**
   - Có. Truy vấn `sum by (instance) (rate(http_requests_total{job="agent",route="/ask"}[3m]))` cho thấy 3 instance nhận lưu lượng gần như bằng nhau: `172.27.0.4:8000` (`13.48 req/s`), `172.27.0.8:8000` (`13.50 req/s`), `172.27.0.9:8000` (`13.21 req/s`) nhờ Nginx round-robin + Docker DNS discovery.
3. **Vì sao `input tokens/s` lớn hơn `output tokens/s`?**
   - Đo thực tế: `input = 3098.7 tokens/s` vs `output = 1629.8 tokens/s` (gần gấp đôi). Nguyên nhân là với agent v2 (RAG), mỗi request phải gửi vào LLM toàn bộ `SYSTEM_PROMPT` + tài liệu context lấy từ `KNOWLEDGE_BASE` + câu hỏi của user, nên số input tokens lớn hơn hẳn câu trả lời ngắn gọn ở output.
4. **`curl http://localhost:8080/metrics` trả về gì? Vì sao?**
   - Trả về **`HTTP/1.1 404`** (Nginx chủ động chặn đường dẫn `/metrics` từ bên ngoài để tránh lộ thông tin nội bộ và ngăn lạm dụng scrape; chỉ Prometheus nằm trong mạng nội bộ `obs_net` mới gọi trực tiếp `agent:8000/metrics`).

### Unit test alert rules (`promtool`)
- Chạy `promtool test rules /p/alert_rules_test.yml` với `prom/prometheus:v3.16.0`: **PASS** toàn bộ test cases.

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`) | **70.2 giây** | Golden Signals → **Error rate** (đỏ, > 20%) & Latency/Traffic → `5xx req/s` |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`) | **130.4 giây** | Golden Signals → **p95 Latency** (> 1.6s) & **Latency p50/p95/p99** |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`) | **Đang firing** (burn rate > $2/giờ do tải cao + model large đắt ~16×) | Golden Signals → **Cost 1h** & LLM → **Cost USD/giờ** |
| D | `docker pause` 1 instance (`agent-4`) | `AgentInstanceDown` (`for: 30s`) | **40.1 giây** (từ lúc `docker pause`) | Golden Signals → **Instances up** giảm từ 2 → 1; Requests/s của instance bị pause tụt về 0 |
| E | `AGENT_VERSION=v1` | **Không có alert nào firing** | N/A | LLM → **Retrieval hit ratio** tụt về 0%, `tokens/s` giảm, bảng **Instances / Version** chuyển sang `v1` |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Observability hạ tầng (latency, error rate, uptime) chỉ đo **hệ thống có chạy nhanh và không lỗi 5xx hay không**, không biết câu trả lời có **đúng** hay không. Để phát hiện sự cố tụt chất lượng như Thí nghiệm E trong production, cần kết hợp:
1. **CI/CD Eval Quality Gate:** chạy tự động `eval/run_eval.py` trên golden dataset với `--baseline` và `--min-accuracy` trước mọi lần merge/deploy (chặn ngay phiên bản bị regression).
2. **Online evaluation & sampling:** lấy mẫu traffic production (vd 5–10%) chấm tự động bằng LLM-as-a-judge hoặc bộ kiểm tra rule-based và xuất thành custom metric (vd `agent_eval_accuracy_score`) để đặt alert.
3. **Business / RAG metrics & User feedback:** theo dõi `retrieval_hit_ratio` (tụt bất thường khi chuyển sang v1), tỉ lệ thumbs-down / retry của người dùng, và chạy canary rollout / A/B test trước khi đẩy 100% traffic.

### 4.3 Debug bằng trace

Chọn trace chậm nhất tìm được trong Jaeger (`http://localhost:16686/trace/1a4c41c97b41f50046343598987052f7`):

- `trace_id`: `1a4c41c97b41f50046343598987052f7`
- Tổng thời gian (`POST /ask`): **1697.52 ms** (trong đó `agent.run` = 1694.97 ms, `agent.retrieve_context` = 22.78 ms / 1.3%)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**1671.95 ms**, chiếm **98.5%**) → chứng tỏ nguyên nhân chậm đến từ upstream LLM call (tail latency), không phải do code xử lý hay bước retrieval của agent.
- Dòng log JSON tương ứng (grep `docker compose -p k5-day14-observability logs agent | grep 1a4c41c97b41f50046343598987052f7`):

```json
{"ts": "2026-11-25T09:19:04.122352+00:00", "level": "INFO", "service": "observable-agent", "instance": "0e4423ee5793", "event": "llm_call", "trace_id": "1a4c41c97b41f50046343598987052f7", "span_id": "33a6b4187057ebbe", "request_id": "cc507836f4db", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 83, "output_tokens": 44, "cost_usd": 3.9e-05, "llm_ms": 1671.7}
```

Trace lỗi đối chiếu (`http://localhost:16686/trace/7ad2b8875602fcbd91d949b30c1acfb2`):

```json
{"ts": "2026-11-25T09:19:02.410341+00:00", "level": "INFO", "service": "observable-agent", "instance": "0e4423ee5793", "event": "llm_error", "trace_id": "7ad2b8875602fcbd91d949b30c1acfb2", "span_id": "0b59ecb2d10c110e", "request_id": "81a0cb5bd2ba", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Nguồn dữ liệu: `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv` (dòng `Aggregated` — và ghi chú riêng `POST /ask`).

| Số instance | RPS (Aggregated / `/ask`) | p50 (ms) | p95 (ms) (Agg / `/ask`) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 66.11 / 60.16 | 190 | 240 / 250 | 1700 | 66 / 7834 (0.84%) |
| 3 | 65.16 / 59.53 | 190 | 240 / 250 | 1700 | 74 / 7738 (0.96%) |

**Giải thích kết quả:** Scale từ 1 lên 3 instance **không làm giảm p95 (vẫn 240–250 ms) và RPS giữ nguyên (~65–66 RPS)**. Có 2 nguyên nhân chính:
1. **Nút thắt nằm ở upstream LLM latency (I/O-bound), không phải CPU của FastAPI agent:** Như trace trong Jaeger đã chứng minh, 98.5% thời gian xử lý nằm ở bước chờ phản hồi từ LLM (`~120–180 ms` + 3% tail latency `+1500 ms`). Thêm container agent giúp tăng khả năng chịu tải đồng thời (headroom) và tính sẵn sàng cao (high availability khi 1 node chết), nhưng **không thể làm upstream LLM trả lời nhanh hơn**.
2. **Tải đầu vào bị giới hạn bởi `wait_time` của 100 Locust user:** Mỗi virtual user nghỉ giữa các request nên 100 user chỉ sinh tối đa ~65–66 RPS — mức này 1 instance `async` FastAPI đã xử lý dư sức mà chưa bị nghẽn CPU hay hàng đợi.

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Đừng tin vào latency trung bình (average) hay chỉ nhìn metric hạ tầng:** Tail latency (`p95`/`p99`) mới phản ánh trải nghiệm thật của nhóm người dùng bị chậm, và metric hạ tầng xanh toàn bộ vẫn có thể bỏ lọt lỗi suy giảm chất lượng câu trả lời (như đổi sang `v1`) nếu không có eval tự động trên golden dataset.
  2. **Ba trụ cột Metrics – Traces – Logs phải liên kết chặt với nhau:** Prometheus/Grafana phát hiện *có bất thường* (alert firing / p95 tăng), Jaeger trace chỉ ra *chậm hay lỗi ở span nào* (`chat mock-llm-small` chiếm 98.5%), và `trace_id` trong JSON log nối thẳng tới chi tiết request để debug trong vài giây.
  3. **Scale ngang chỉ giải quyết nút thắt CPU/concurrency ở tầng app, không giải quyết latency của upstream LLM:** Phải đo đạc thực tế trước khi tối ưu — với hệ thống AI agent I/O-bound, để giảm p95/p99 hiệu quả hơn cần dùng semantic caching (Redis), streaming response, timeout + fallback model, hoặc prompt ngắn gọn hơn.
- **Nếu đưa agent này lên production thật, cần thêm các metric / alert sau:**
  - **Metrics:** `nginx_http_requests_total` (bắt lỗi 502/504 từ tầng Load Balancer mà metric trong agent không thấy), `agent_cache_hit_ratio` (hiệu quả Redis cache), `llm_ttft_seconds` (Time To First Token cho streaming), `agent_eval_online_score` (chất lượng mẫu online), và `redis_connected_clients` / `redis_memory_used_bytes`.
  - **Alerts:** Burn-rate alert đa cửa sổ (multi-window SLO error budget alert), alert `RetrievalHitRatioDrop` (phát hiện sớm lỗi RAG/KB bị rỗng), alert khi tỷ lệ `429 Rate Limited` hoặc `402 Budget Exceeded` tăng đột biến (phát hiện abuse/DDoS hoặc sắp chạm trần ngân sách).
