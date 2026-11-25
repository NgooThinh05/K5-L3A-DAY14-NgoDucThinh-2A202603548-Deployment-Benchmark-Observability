# Day 14 Lab — Mission Answers

> **Họ và tên:** Ngô Đức Thịnh  
> **MSSV:** 2A202603548  
> **Lớp:** K5-L3A

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns tìm thấy trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trong source code** (dòng 17–18): `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Nếu push lên GitHub sẽ lộ credential ngay lập tức.
2. **Hardcode cấu hình, không tách khỏi code** (dòng 21–22): `DEBUG = True`, `MAX_TOKENS = 500` ghi cứng thay vì đọc từ biến môi trường, không linh hoạt giữa dev/staging/production.
3. **Dùng `print()` thay cho structured logging và log trực tiếp secret** (dòng 33–34, 38): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` làm lộ API key ra log và không thể parse/filter trên hệ thống log aggregator (Loki, Datadog).
4. **Không có Health Check / Readiness endpoint**: Không có `/health` hay `/ready`, nên cloud platform/orchestrator không biết container còn sống hay sẵn sàng nhận traffic để restart hoặc route.
5. **Bind `localhost`, cứng port `8000` và bật `reload=True`** (dòng 49–54): `host="localhost"` khiến bên ngoài container không truy cập được; cứng `port=8000` không tương thích với `PORT` do Railway/Render cấp; `reload=True` lãng phí tài nguyên và không an toàn trong production.
6. **Không xử lý Graceful Shutdown**: Khi platform gửi `SIGTERM`, process tắt đột ngột, cắt ngang các request đang xử lý.

### Exercise 1.2: Kết quả chạy bản `develop`

Lệnh test (nhận `question` qua query string):
```bash
curl -sS -i -X POST "http://localhost:8000/ask?question=Hello"
```
Output thực tế:
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:49:46 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 1.3: Bảng so sánh `develop` vs `production`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Tại sao quan trọng? |
| :--- | :--- | :--- | :--- |
| **Config & Secrets** | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG`, `PORT` trong code (dòng 17–22, 52) | Đọc toàn bộ từ env vars qua `Settings` (`config.py`), có `.validate()` fail-fast | Tránh lộ secret lên Git, dễ đổi cấu hình giữa dev/staging/prod mà không sửa code (12-Factor). |
| **Network binding** | `host="localhost"`, `port=8000`, `reload=True` (dòng 51–53) | `host="0.0.0.0"`, `port=int(os.getenv("PORT", 8000))`, `reload=settings.debug` (dòng 196–198) | Trong container phải bind `0.0.0.0` mới nhận được traffic ngoài; cloud platform cấp `PORT` động. |
| **Health & Readiness** | Không có | Có `GET /health` (liveness, dòng 135) và `GET /ready` (readiness trả 503 khi chưa sẵn sàng, dòng 152) | Platform dùng `/health` để tự restart khi treo, load balancer dùng `/ready` để chỉ route vào instance sẵn sàng. |
| **Logging** | `print()` plain text, in cả `OPENAI_API_KEY` (dòng 33–34) | `logging` xuất JSON có cấu trúc, chỉ log metadata (`question_length`, `client_ip`), không log secret (dòng 28–32, 111–122) | Bảo mật secret, dễ tìm kiếm/cảnh báo tự động bằng ELK/Loki/Datadog. |
| **Shutdown** | Tắt đột ngột | Có `lifespan` (dòng 39–67) đặt `is_ready = False` và bắt `SIGTERM` (dòng 180–189) | Cho phép request đang chạy hoàn tất trước khi tắt container (zero-downtime deploy). |
| **Input & CORS** | Query param đơn giản, không có CORS | JSON body với validation trả 422, cấu hình `CORSMiddleware` theo `ALLOWED_ORIGINS` | Chuẩn hóa API contract và kiểm soát domain được phép gọi API. |

Kết quả test bản `production`:
```json
GET /health -> {"status":"ok","uptime_seconds":1.5,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T07:49:48.958157+00:00"}
GET /ready  -> {"ready":true}
POST /ask   -> {"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}
```

---

## Part 2: Docker

### Exercise 2.1: Trả lời câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` (full Debian + Python distribution, dung lượng lớn ~1 GB).
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Tại sao `COPY requirements.txt` đứng trước `COPY app.py`?** Để tận dụng **Docker layer cache**. Source code (`app.py`) thay đổi thường xuyên hơn `requirements.txt`. Khi copy và `pip install` trước, Docker giữ nguyên layer dependencies đã cache nếu `requirements.txt` không đổi, giúp rebuild rất nhanh.
4. **Sự khác nhau giữa `CMD` và `ENTRYPOINT`:**
   - `ENTRYPOINT` định nghĩa **lệnh chính cố định** của container (khó bị ghi đè trừ khi truyền `--entrypoint`).
   - `CMD` cung cấp **lệnh mặc định hoặc tham số mặc định** cho `ENTRYPOINT`, và dễ dàng bị ghi đè khi truyền đối số ở cuối lệnh `docker run`.

### Exercise 2.2 & 2.3: Multi-stage build và so sánh kích thước image đo thực tế

**Phân tích `02-docker/production/Dockerfile`:**
- **Stage 1 (`builder`):** Dùng `python:3.11-slim`, cài công cụ biên dịch (`gcc`, `libpq-dev`) và chạy `pip install --no-cache-dir --user -r requirements.txt` vào `/root/.local`.
- **Stage 2 (`runtime`):** Bắt đầu mới từ `python:3.11-slim`, tạo non-root user `appuser`, chỉ `COPY --from=builder /root/.local` (các package đã biên dịch) cùng source code, thêm `HEALTHCHECK` và chạy `uvicorn`.
- **Tại sao image nhỏ hơn?** Dùng base `-slim` thay vì full `python:3.11`, đồng thời **bỏ lại toàn bộ build tools** (`gcc`, `libpq-dev`, apt cache, pip cache) ở Stage 1 nên Stage 2 chỉ chứa đúng runtime cần thiết.

**Số liệu đo thực tế bằng `docker images my-agent`:**
- `my-agent:develop`: **1.15 GB** (~1150 MB)
- `my-agent:advanced`: **163 MB**
- **Chênh lệch:** Giảm **~987 MB**, tương đương giảm **85.8%** (nhỏ hơn ~7 lần).

### Exercise 2.4: Docker Compose stack (`02-docker/production/`)

**Sơ đồ kiến trúc các service:**
```text
Client (HTTP :80)
   │
   ▼
┌────────────────────────────┐
│  nginx (nginx:alpine)      │  ← Reverse proxy, rate limit 10r/s, security headers
└─────────────┬──────────────┘
              │ (internal bridge network)
              ▼
┌────────────────────────────┐
│  agent (FastAPI :8000)     │  ← Không expose port ra ngoài
└──────┬──────────────┬──────┘
       │              │
       ▼              ▼
┌─────────────┐ ┌──────────────────┐
│ redis :6379 │ │ qdrant :6333     │  ← Persistent volumes: redis_data, qdrant_data
└─────────────┘ └──────────────────┘
```

**Kết quả test thực tế qua Nginx (`http://localhost`):**
```http
$ curl -sS -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":5.3,"version":"2.0.0","timestamp":"2026-11-25T07:55:44.938046"}

$ curl -sS -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy agent Part 6 (`06-lab-complete/`)

- **Platform chính:** Railway (`agent` + Managed `Redis`)
- **Public URL:** https://agent-production-5016b0b3.up.railway.app
- **Screenshots:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`

### So sánh `railway.toml` vs `render.yaml`

| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) |
| :--- | :--- | :--- |
| **Định dạng & phạm vi** | TOML, cấu hình cho **1 service** hiện tại (`[build]`, `[deploy]`). | YAML (Infrastructure as Code), có thể khai báo **nhiều service** (web, worker, database/Redis) trong cùng 1 file. |
| **Cách build Docker** | `builder = "DOCKERFILE"`, `dockerfilePath = "Dockerfile"`. | `runtime: docker`, `dockerfilePath: ./Dockerfile`. |
| **Health check** | `healthcheckPath = "/health"`, `healthcheckTimeout = 30`. | `healthCheckPath: /health`. |
| **Quản lý biến môi trường / Secret** | Thường cấu hình qua Railway Dashboard hoặc CLI (`railway variables set`), không khai báo secret trong file. | Khai báo trực tiếp trong mục `envVars:` với `generateValue: true` (tự sinh secret) hoặc `sync: false` (nhập tay trên dashboard, không lộ vào Git). |
| **Restart policy** | Hỗ trợ khai báo trực tiếp `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3`. | Render tự quản lý restart khi health check fail, không cần cấu hình thủ công trong Blueprint. |

### Exercise 3.3: Phân tích CI/CD pipeline GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)

Pipeline trong `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` tự động chạy 4 bước tuần tự khi có commit lên nhánh chính:
1. **Test (`test`):** Dùng image `python:3.11-slim` để cài dependencies và chạy `pytest tests/`; nếu test fail sẽ dừng pipeline ngay.
2. **Build (`build`):** Dùng `gcr.io/cloud-builders/docker` build Docker image gắn 2 tag (`$COMMIT_SHA` và `latest`) có tận dụng `--cache-from` để tăng tốc.
3. **Push (`push`):** Đẩy toàn bộ tag image vừa build lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **Deploy (`deploy`):** Dùng `gcloud run deploy` triển khai image theo đúng `$COMMIT_SHA` lên Cloud Run (`asia-southeast1`), cấu hình autoscale (`min-instances=1` tránh cold start, `max-instances=10`), giới hạn tài nguyên (`512Mi`, `1 CPU`), và nạp secret từ **Secret Manager** (tương ứng đặc tả IaC trong `service.yaml` gồm `containerConcurrency: 80`, `livenessProbe /health`, `startupProbe /ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/`)

- API key được kiểm tra trong dependency `verify_api_key` đọc header `X-API-Key` và gắn vào `/ask` qua `Depends(verify_api_key)`.
- Nếu thiếu key → trả **401 Unauthorized**; nếu sai key → trả **403 Forbidden** (trong bản Part 6 chuẩn hóa đều trả **401**).
- Để rotate key an toàn: cập nhật biến môi trường `AGENT_API_KEY` trên nền tảng (hoặc hỗ trợ danh sách key cũ + mới song song trong thời gian chuyển đổi rồi thu hồi key cũ).

**Output test thực tế (`AGENT_API_KEY=secret-key-123`):**
```http
# Không có API key -> 401
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Có API key hợp lệ -> 200
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **Thuật toán Rate Limiting (`rate_limiter.py`):** **Sliding Window Counter** sử dụng `deque` lưu timestamp các request trong cửa sổ `60` giây, tự động loại bỏ timestamp quá hạn trước khi đếm.
- **Giới hạn:** Role `user` (`student`) = **10 requests/phút**; role `admin` (`teacher`) = **100 requests/phút** (có thể bypass/tăng hạn mức dựa trên trường `role` trích xuất từ payload JWT).
- **Lấy token tại `POST /auth/token`** với tài khoản `student` / `demo123` (đã che token trước khi dán).

**Output test thực tế (`curl -i`):**
```http
# Không có JWT token -> 401
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
content-type: application/json

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Request 1 với Bearer <REDACTED_JWT_TOKEN> -> 200
HTTP/1.1 200 OK
content-type: application/json

{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}

# Vòng lặp gửi liên tiếp:
# Req 2..10 -> HTTP 200
# Req 11 -> HTTP 429 Too Many Requests
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795593182
retry-after: 59
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cách triển khai Cost Guard

- **Tại sao cần cả Rate Limit và Cost Guard?** Rate limit chỉ khống chế **tốc độ gọi** (requests/phút), còn Cost Guard khống chế **tổng chi phí tiền** (USD/ngày hoặc USD/tháng), tránh trường hợp user gửi ít request nhưng mỗi request có prompt/output rất dài gây đội chi phí LLM.
- **Cách triển khai chuẩn production (dùng Redis như trong Part 6):**
  1. Trước khi gọi LLM (`check_budget()`): đọc tổng chi phí đã dùng từ Redis theo key theo ngày (`cost:daily:YYYY-MM-DD`) và theo tháng (`cost:monthly:YYYY-MM`). Nếu đạt hoặc vượt ngưỡng `DAILY_BUDGET_USD` / `MONTHLY_BUDGET_USD` → lập tức trả **HTTP 402 Payment Required**.
  2. Sau khi gọi LLM (`record_cost(input_tokens, output_tokens)`): tính chi phí theo đơn giá token (`PRICE_INPUT_PER_1K`, `PRICE_OUTPUT_PER_1K`), cộng dồn nguyên tử vào Redis bằng `INCRBYFLOAT` và đặt `EXPIRE` (2 ngày cho daily key, 35 ngày cho monthly key) để tự động reset sang chu kỳ mới.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health Check, Readiness & Graceful Shutdown (`05-scaling-reliability/develop/`)

- **Phân biệt `/health` (Liveness) và `/ready` (Readiness):**
  - `/health` kiểm tra **process còn sống không** (không phụ thuộc Redis/DB bên ngoài) — nếu fail, orchestrator sẽ restart container.
  - `/ready` kiểm tra **service đã sẵn sàng nhận traffic chưa** (đã load xong model, kết nối được Redis/DB, chưa vào trạng thái shutdown) — nếu trả **503**, load balancer tạm ngắt traffic khỏi instance đó mà không kill container.
- **Kết quả test `05-scaling-reliability/develop`:**
  ```json
  GET /health -> {"status":"ok","uptime_seconds":1.0,"version":"1.0.0","environment":"development","checks":{"memory":{"status":"ok","used_percent":26.0}}}
  GET /ready  -> {"ready":true,"in_flight_requests":1}
  ```
  Khi nhận `SIGTERM` (`kill -TERM`), app ghi nhận signal để tiến hành graceful shutdown (lưu ý quan trọng: nếu tự đăng ký `signal.signal(SIGTERM, ...)`, bắt buộc gọi lại handler gốc của uvicorn thì process mới thoát êm được).

### Exercise 5.3–5.5: Stateless Design & Load Balancing 3 Instances (`05-scaling-reliability/production/`)

- **Tại sao không lưu state trong RAM?** Khi chạy nhiều instance sau load balancer, request 1 có thể vào `instance-A` còn request 2 vào `instance-B`. Nếu lưu lịch sử chat / rate limit trong dict RAM thì mỗi instance giữ một bản khác nhau, dẫn đến mất ngữ cảnh hội thoại và vượt rate limit. Chuyển toàn bộ state sang **Redis dùng chung** giúp mọi instance đều stateless và thay thế được cho nhau.
- **Kết quả chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` và `python test_stateless.py`:**
  ```text
  NAME                       SERVICE   STATUS                    PORTS
  k5-day14-scaling-agent-1   agent     Up 9 seconds (healthy)    8000/tcp
  k5-day14-scaling-agent-2   agent     Up 9 seconds (healthy)    8000/tcp
  k5-day14-scaling-agent-3   agent     Up 8 seconds (healthy)    8000/tcp
  k5-day14-scaling-nginx-1   nginx     Up 8 seconds              0.0.0.0:8080->80/tcp
  k5-day14-scaling-redis-1   redis     Up 20 seconds (healthy)   6379/tcp

  Session ID: c125ed55-435f-4c30-92a0-41f657a648ba
  Request 1: [instance-f56e4d] -> Q: What is Docker?
  Request 2: [instance-ece011] -> Q: Why do we need containers?
  Request 3: [instance-9fb9bb] -> Q: What is Kubernetes?
  Request 4: [instance-f56e4d] -> Q: How does load balancing work?
  Request 5: [instance-ece011] -> Q: What is Redis used for?

  Total requests: 5
  Instances used: {'instance-9fb9bb', 'instance-ece011', 'instance-f56e4d'}
  ✅ All requests served despite different instances!

  --- Conversation History ---
  Total messages: 10
  ✅ Session history preserved across all instances via Redis!
  ```
- **Giải thích kết quả:** Nginx phân tán 5 request tuần tự theo kiểu round-robin tới đủ cả 3 container agent (`instance-f56e4d`, `instance-ece011`, `instance-9fb9bb`), nhưng khi truy vấn `/chat/{session_id}/history` vẫn nhận đủ toàn bộ 10 tin nhắn (5 user + 5 assistant) vì session history được đọc/ghi tập trung trên Redis.

---

## Part 6: Final Project (`06-lab-complete/`) — Kết quả `check_production_ready.py`

Chạy trong WSL2 Ubuntu (`os.name == 'posix'`), đầy đủ cả runtime, Redis, Docker build/run/stop (image size **201 MB**, `docker stop` exit code `0` trong **1.0s**):

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

---

## AI Log

- **Công cụ sử dụng:** Antigravity AI Assistant.
- **Nội dung hỗ trợ:**
  1. Hướng dẫn thiết lập môi trường Python virtualenv trong WSL2 Ubuntu (`posix`) để tương thích `SIGTERM` trên Windows.
  2. Hỗ trợ viết code hoàn thiện các `TODO` trong `06-lab-complete/` (`app/config.py`, `app/redis_client.py`, `app/auth.py`, `app/rate_limiter.py`, `app/cost_guard.py`, `app/main.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`), bổ sung 2 mục `KNOWLEDGE_BASE` trong `mock_llm.py` cho Exercise 7.3 và thêm `ENV PYTHONUSERBASE` trong `production/Dockerfile` của Part 7 để sửa lỗi tìm module `uvicorn`.
  3. Hỗ trợ tổng hợp câu trả lời vào `MISSION_ANSWERS.md`, `DEPLOYMENT.md` và `BENCHMARK_REPORT.md` dựa trên kết quả chạy thực tế.
- **Tự kiểm tra & xác minh:** Toàn bộ các số đo (kích thước image `1.15GB` vs `163MB` ở Part 2, output HTTP `401`/`200`/`429` ở Part 4, kết quả 3 instance & 10 messages ở Part 5, `PASS 12/12` · `43/43 checks passed` với image `201 MB` ở Part 6, 4 lệnh `curl` live `200/200/401/200` trên Railway ở CP6, và toàn bộ 10 file JSON, 2 file CSV Locust, trace/log Jaeger, 4 alert firing trên Prometheus ở Part 7) đều được chạy và kiểm chứng trực tiếp trên máy cá nhân.
