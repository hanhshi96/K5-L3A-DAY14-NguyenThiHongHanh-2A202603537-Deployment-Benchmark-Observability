# Deployment Information

## Public URL
https://agent-production-8d68483d.up.railway.app

## Platform
**Railway** — project `day14-agent`, 2 service:

| Service | Nguồn | Ghi chú |
|---|---|---|
| `agent` | Build từ `06-lab-complete/Dockerfile` (`railway up` trong `06-lab-complete/`) | Cấu hình bởi `06-lab-complete/railway.toml`: `builder = "DOCKERFILE"`, `healthcheckPath = "/health"`, restart khi lỗi |
| `Redis` | Railway Database (`redis:8.2`) | Dùng cho rate limit + cost guard; agent kết nối qua mạng nội bộ `redis.railway.internal` |

## Test Commands

Đặt biến (key lấy từ Railway → service `agent` → Variables, hoặc `railway variables --service agent`):
```bash
BASE=https://agent-production-8d68483d.up.railway.app
AGENT_API_KEY=YOUR_KEY
```

### Health Check
```bash
curl $BASE/health
# Expected: {"status":"ok","uptime_seconds":...,"environment":"production"}

curl $BASE/ready
# Expected: {"ready":true,"redis":"ok"}
```

### API Test (with authentication)
```bash
# Không có key → 401
curl -X POST $BASE/ask \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'

# Có key → 200
curl -X POST $BASE/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
```

### Kết quả tự kiểm (CP6) — 2026-11-25
```text
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
200
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
200
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'
401
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'
200
```
Response mẫu:
```text
GET  /health → {"status":"ok","uptime_seconds":26.1,"environment":"production"}
GET  /ready  → {"ready":true,"redis":"ok"}
POST /ask    → {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","usage":{"cost_usd":1.2e-05}}
```
`python check_production_ready.py --public-url https://agent-production-8d68483d.up.railway.app` → `✅ Public URL: GET .../health → 200`

## Environment Variables Set
Đặt trên Railway (service `agent` → Variables), **không ghi trong code hay file commit**:

| Biến | Giá trị / nguồn |
|---|---|
| `AGENT_API_KEY` | Secret ngẫu nhiên 48 ký tự (`openssl rand -hex 24`), chỉ lưu trên Railway |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` — Railway tự điền URL của service Redis |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `PORT` | Railway tự cấp; `CMD` trong Dockerfile dùng `${PORT:-8000}` |

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
