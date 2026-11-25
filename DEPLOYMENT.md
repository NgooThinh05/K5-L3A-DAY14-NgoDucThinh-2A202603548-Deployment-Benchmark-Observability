# Deployment Information

## Public URL
https://agent-production-5016b0b3.up.railway.app

## Platform
Railway (Docker service `agent` + Managed `Redis`)

## Test Commands (CP6 Self-Check)

Đặt biến `BASE` và `AGENT_API_KEY` (không commit key thật vào repo):

```bash
export BASE="https://agent-production-5016b0b3.up.railway.app"
export AGENT_API_KEY="<YOUR_SECRET_KEY>"

# 1. Health check (Expected: 200)
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"

# 2. Readiness check với Redis (Expected: 200)
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"

# 3. Gọi /ask không có API key (Expected: 401)
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'

# 4. Gọi /ask có API key hợp lệ (Expected: 200)
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
```

### Verified Live Output
```text
1. GET /health              -> 200  {"status":"ok","environment":"production"}
2. GET /ready               -> 200  {"status":"ready","redis":"ok"}
3. POST /ask (no key)       -> 401  {"detail":"Invalid or missing API key. Include header: X-API-Key"}
4. POST /ask (with API key) -> 200  {"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock)...","cost_usd":1.035e-05,"environment":"production"}
```

## Environment Variables Set on Platform
- `PORT` (tự động cấp bởi nền tảng)
- `ENVIRONMENT=production`
- `AGENT_API_KEY` (đặt trong dashboard/CLI của nền tảng, không ghi vào code)
- `REDIS_URL` (trỏ tới Redis service trên nền tảng)
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`
- `MONTHLY_BUDGET_USD=10.0`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
