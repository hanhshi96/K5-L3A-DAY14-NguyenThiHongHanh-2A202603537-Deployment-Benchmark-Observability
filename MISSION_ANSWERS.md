# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found
File: `01-localhost-vs-production/develop/app.py`

1. **Hardcode secret** (dòng 17-18): `OPENAI_API_KEY` và `DATABASE_URL` (có cả mật khẩu) viết thẳng trong code → push lên GitHub là lộ key/mật khẩu.
2. **Log ra secret** (dòng 34): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` → ai đọc được log là thấy key.
3. **Dùng `print()` thay vì logging có cấu trúc** (dòng 33, 38): không có level (info/error), không có thời gian, không phải JSON → khó tìm kiếm và phân tích log khi chạy production.
4. **Config cứng trong code** (dòng 21-22): `DEBUG = True`, `MAX_TOKENS = 500` → muốn đổi phải sửa code và deploy lại, thay vì đọc từ biến môi trường (12-Factor).
5. **Không có health check endpoint** (dòng 42-43): không có `/health` → khi agent treo/crash, nền tảng cloud không biết để restart.
6. **`host="localhost"`** (dòng 52): chỉ nhận kết nối từ chính máy đó → chạy trong container hoặc trên cloud thì bên ngoài không gọi vào được (cần `0.0.0.0`).
7. **Port cố định 8000** (dòng 53): không đọc biến môi trường `PORT` → Railway/Render inject port khác thì app không nhận request.
8. **`reload=True`** (dòng 54): chế độ tự reload khi sửa code chỉ dành cho lúc dev, tốn tài nguyên và không ổn định trong production.
9. **Không có graceful shutdown**: không xử lý tín hiệu SIGTERM → khi platform tắt/redeploy, request đang xử lý bị cắt ngang.

### Exercise 1.2: Kết quả chạy bản develop
```text
$ curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}

$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found
```

Log của server (trích):
```text
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [61181] using WatchFiles
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.
```

**Quan sát:** App chạy và trả lời được, nhưng chưa production-ready:
- Log in thẳng API key ra màn hình (`Using key: sk-...`) → lộ secret.
- `/health` trả **404** → platform không có cách kiểm tra agent còn sống.
- Chạy ở `localhost` với reloader bật (`Started reloader process`) → chế độ dev, không dùng được trong container/cloud.

### Exercise 1.3: Comparison table
| Feature | Develop | Production | Why Important? |
|---------|---------|------------|----------------|
| Config | Hardcode trong code (`OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG`, port 8000) | Đọc từ biến môi trường qua `config.py` (`PORT`, `HOST`, `DEBUG`, `AGENT_API_KEY`...), có `.env.example` làm mẫu | Không lộ secret khi push code; cùng một code chạy được ở dev/staging/prod chỉ bằng cách đổi env (12-Factor) |
| Health check | Không có — `/health` trả 404 | `/health` (liveness) trả 200 + uptime; `/ready` (readiness) trả 200 khi sẵn sàng, 503 khi chưa | Platform biết agent còn sống để restart khi treo; load balancer chỉ gửi traffic vào instance đã sẵn sàng |
| Logging | `print()`, in cả API key ra log | `logging` theo format JSON, chỉ log metadata (độ dài câu hỏi, IP), không log secret | Log JSON dễ tìm kiếm/lọc trong công cụ log (Loki, Datadog); không làm lộ secret |
| Shutdown | Đột ngột — không xử lý tín hiệu tắt | Graceful: bắt SIGTERM, `lifespan` đặt `is_ready=False` rồi chờ request đang chạy xong | Khi redeploy/scale down không cắt ngang request của người dùng |
| Host / Port | `localhost:8000` cố định, `reload=True` | `0.0.0.0`, port từ env `PORT`, reload chỉ khi `DEBUG=true` | Chạy được trong container và trên cloud (Railway/Render tự gán `PORT`) |

Kết quả chạy bản production:
```text
$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":1.0,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T07:34:45.584855+00:00"}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true}
```
Log server chạy ở `0.0.0.0:8000` và không còn dòng nào in ra API key.

**Quan sát thêm về logging:** Khi chạy thực tế, các dòng log JSON (`{"event":"agent_request",...}`) **không xuất hiện**, chỉ thấy `WARNING:root:OPENAI_API_KEY not set — using mock LLM` theo format mặc định. Nguyên nhân: `app.py` import `config` (dòng 24) **trước** `logging.basicConfig(...)` (dòng 28). Khi import, `config.validate()` gọi `logging.warning(...)` → Python tự cấu hình root logger với level mặc định WARNING. Vì root logger đã có handler, `basicConfig` ở dòng 28 trở thành no-op → format JSON và level INFO không được áp dụng, mọi log INFO bị bỏ. Cách sửa: gọi `logging.basicConfig(...)` trước khi import `config`, hoặc thêm `force=True` vào `basicConfig`. Bài học: thứ tự khởi tạo logging rất quan trọng, nên kiểm tra log thật chứ không chỉ đọc code.

## Part 2: Docker

### Exercise 2.1: Dockerfile questions
File: `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` (dòng 8) — bản Python đầy đủ (~1 GB), app được xây trên nền này.
2. **Working directory:** `/app` (dòng 11) — mọi lệnh `COPY`/`RUN`/`CMD` sau đó chạy trong thư mục này bên trong container.
3. **Tại sao COPY requirements.txt trước:** Docker cache từng layer. `requirements.txt` ít thay đổi còn code thay đổi liên tục. Copy requirements + `pip install` trước (dòng 14-17), code sau (dòng 20) → khi chỉ sửa code, Docker dùng lại layer cài thư viện đã cache, build nhanh hơn nhiều. Nếu copy code trước thì mỗi lần sửa code đều phải cài lại toàn bộ thư viện.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh *mặc định*, có thể bị ghi đè khi `docker run <image> <lệnh khác>`. `ENTRYPOINT` là lệnh *cố định* luôn chạy, phần thêm sau `docker run` chỉ được nối vào làm tham số. Dockerfile này dùng `CMD ["python", "app.py"]` (dòng 30).

### Exercise 2.2: Build và run
```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .    # chạy từ gốc repo, ~1 phút 12 giây lần đầu
$ docker run -d --rm --name k5-p2-develop -p 8000:8000 my-agent:develop

$ curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker?"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":0.3,"container":true}

$ docker images my-agent:develop
IMAGE              ID             DISK USAGE   CONTENT SIZE   EXTRA
my-agent:develop   d0065090a966       1.67GB          415MB   U
```
Image develop: **1.67 GB** trên đĩa (content size nén 415 MB) — rất nặng vì base `python:3.11` là bản đầy đủ.

### Exercise 2.3: Image size comparison
File: `02-docker/production/Dockerfile` (multi-stage)

- **Stage 1 (`builder`, dòng 16-29):** từ `python:3.11-slim`, cài build tools (`gcc`, `libpq-dev`) rồi `pip install --user` các thư viện vào `/root/.local`. Stage này **không** được dùng để deploy.
- **Stage 2 (`runtime`, dòng 36-72):** lại từ `python:3.11-slim` sạch, chỉ `COPY --from=builder` thư mục thư viện đã cài + code. Chạy bằng user thường `appuser` (không phải root), có `HEALTHCHECK`.
- **Tại sao nhỏ hơn:** (1) base `python:3.11-slim` thay vì `python:3.11` đầy đủ; (2) build tools (`gcc`, apt cache) chỉ nằm ở stage 1 và bị bỏ đi, không vào image cuối.

```text
$ docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
$ docker images | grep my-agent
IMAGE                ID             DISK USAGE   CONTENT SIZE
my-agent:advanced    df846a3ab3c3        265MB         57.5MB
my-agent:develop     d0065090a966       1.67GB          415MB
```

- Develop: **1670 MB** (1.67 GB disk usage; content 415 MB)
- Production: **265 MB** (disk usage; content 57.5 MB)
- Difference: **giảm 84.1%** theo disk usage, `(1670 − 265) / 1670` (content size giảm 86.1%) — image production nhỏ hơn ~6.3 lần.

Kiểm tra container production chạy được và không chạy bằng root:
```text
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":1.0,"version":"2.0.0","timestamp":"2026-11-25T08:16:07.840194"}
$ docker exec k5-p2-adv whoami
appuser
```

*Ghi chú:* lần build đầu trên Wi-Fi trường bị lỗi `401 VG-AuthenticationRequired` ở bước `apt-get update` (proxy của trường chặn `http://deb.debian.org`); chuyển sang Wi-Fi khác thì build thành công, không sửa Dockerfile.

### Exercise 2.4: Docker Compose stack
File: `02-docker/production/docker-compose.yml`

**Sơ đồ các service:**
```text
                Client (curl)
                     │  :80
                     ▼
            ┌──────────────────┐
            │ nginx            │  reverse proxy + load balancer
            │ (nginx:alpine)   │  rate limit 10 r/s, security headers
            └────────┬─────────┘  — service DUY NHẤT mở port ra ngoài
                     │ http://agent:8000
                     ▼
            ┌──────────────────┐
            │ agent (FastAPI)  │  image multi-stage, healthcheck /health
            └───┬──────────┬───┘  không expose port ra host
 redis://redis:6379   http://qdrant:6333
                ▼          ▼
         ┌──────────┐  ┌──────────┐
         │ redis    │  │ qdrant   │
         │ cache /  │  │ vector DB│
         │ session  │  │ (RAG)    │
         └──────────┘  └──────────┘
   Tất cả cùng network bridge "internal"; redis_data, qdrant_data là volume lưu dữ liệu
```

**Services được start:** `agent`, `redis`, `qdrant`, `nginx`.

**Chúng giao tiếp thế nào:**
- Cùng network nội bộ `internal`, gọi nhau bằng **tên service** (Docker DNS): nginx → `agent:8000`, agent → `redis:6379` và `qdrant:6333`.
- Chỉ nginx publish port 80/443 ra host; agent/redis/qdrant chỉ truy cập được bên trong network → giảm bề mặt tấn công.
- `depends_on` + `condition: service_healthy`: agent chỉ start khi redis và qdrant đã healthy; nginx start sau agent.

**Kết quả test qua Nginx:**
```text
$ docker compose -p k5-day14-docker up -d --build
$ docker compose -p k5-day14-docker ps
SERVICE   IMAGE                   STATUS                    PORTS
agent     k5-day14-docker-agent   Up 6 seconds (healthy)    8000/tcp
nginx     nginx:alpine            Up 6 seconds              0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 17 seconds (healthy)   6333-6334/tcp
redis     redis:7-alpine          Up 17 seconds (healthy)   6379/tcp

$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":5.5,"version":"2.0.0","timestamp":"2026-11-25T08:30:37.278553"}

$ curl -i http://localhost/ask -X POST -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health
000      # agent không mở port ra host → chỉ vào được qua nginx
```
Header `Server: nginx` và các security header (`X-Frame-Options`...) chứng tỏ request đi qua nginx rồi mới tới agent.

## Part 3: Cloud Deployment

### Exercise 3.1: Deploy agent Part 6 lên Railway
- **Nền tảng:** Railway (theo K5: deploy luôn `06-lab-complete/`, không deploy app mẫu `03-cloud-deployment/`)
- **URL:** https://agent-production-8d68483d.up.railway.app
- **Chi tiết + biến môi trường:** xem [DEPLOYMENT.md](DEPLOYMENT.md)
- **Screenshot:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`

Các bước đã làm (trong `06-lab-complete/`):
```bash
railway login
railway init --name day14-agent                 # tạo project, link thư mục
railway add --database redis                    # Redis trên Railway
railway add --service agent \
  --variables 'REDIS_URL=${{Redis.REDIS_URL}}' \
  --variables 'ENVIRONMENT=production' \
  --variables 'RATE_LIMIT_PER_MINUTE=10' \
  --variables 'DAILY_BUDGET_USD=1.0'
railway variables --service agent --set "AGENT_API_KEY=$(openssl rand -hex 24)"   # secret ngẫu nhiên, không in ra
railway up --service agent                      # build bằng Dockerfile theo railway.toml
railway domain --service agent                  # tạo URL public
```

Tự kiểm 4 lệnh của CP6:
```text
/health            → 200
/ready             → 200   {"ready":true,"redis":"ok"}
/ask (không key)   → 401
/ask (có key)      → 200
```

### So sánh railway.toml và render.yaml
| | `railway.toml` | `render.yaml` (Blueprint) |
|---|---|---|
| Định dạng | TOML | YAML |
| Phạm vi | Chỉ cấu hình **build + deploy của 1 service** (`[build] builder = "DOCKERFILE"`, `[deploy] healthcheckPath`, restart policy) | Mô tả **cả hạ tầng**: nhiều service trong 1 file — web service `day14-agent` + Key Value (Redis) `day14-redis` |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout = 30` | `healthCheckPath: /health` |
| Redis | Không khai báo trong file — tạo bằng `railway add --database redis` / dashboard | Khai báo luôn service `type: keyvalue` trong file |
| Biến môi trường | Không nằm trong file; đặt bằng `railway variables` / dashboard. `REDIS_URL` tham chiếu `${{Redis.REDIS_URL}}` | Khai báo trong `envVars`; `REDIS_URL` dùng `fromService` (`property: connectionString`) để Render tự nối |
| Secret | Đặt trực tiếp trên Railway (CLI/dashboard), không có trong repo | `AGENT_API_KEY` dùng `sync: false` → Render hỏi giá trị lúc tạo Blueprint (hoặc `generateValue: true` để Render tự sinh), không ghi giá trị trong file |
| Cách deploy | `railway up` đẩy code từ máy (hoặc nối GitHub) | Push repo lên GitHub → Dashboard → New → Blueprint, Render đọc `render.yaml` |
| Vị trí thư mục | Đặt trong `06-lab-complete/`, chạy `railway up` từ thư mục đó | Có `rootDir: 06-lab-complete` vì Blueprint đọc từ repo, Dockerfile nằm trong thư mục con |
| PORT | Railway cấp `PORT`, Dockerfile đọc `${PORT:-8000}` | Render cũng cấp `PORT`, dùng chung Dockerfile |

**Vì sao khác:** Railway tách "code config" (railway.toml) khỏi "hạ tầng" (tạo service, biến qua CLI/dashboard, nối bằng reference `${{...}}`); Render theo hướng Infrastructure-as-Code: một file Blueprint dựng toàn bộ stack (web + Redis + env) nên tái tạo được đầy đủ từ repo, đổi lại phải khai báo kỹ hơn (`rootDir`, `fromService`, `ipAllowList`). Cả hai đều không ghi secret trong file và đều dùng `/health` để biết deploy thành công.

*Ghi chú:* khi chạy `railway init`, CLI 5.75 cảnh báo "Config as Code (railway.toml) is deprecated… Existing files keep working until 2026-12-01" — Railway đang chuyển sang `.railway/railway.ts`. Bài này vẫn dùng `railway.toml` vì script chấm yêu cầu.

### Exercise 3.3: Pipeline Cloud Run (cloudbuild.yaml + service.yaml)
Pipeline CI/CD trong `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` chạy khi push lên `main`, gồm 4 bước nối tiếp nhau bằng `waitFor`:
1. **test** — trong image `python:3.11-slim`, cài requirements + pytest và chạy `pytest tests/`; test fail thì pipeline dừng, không build.
2. **build** — build Docker image, gắn 2 tag `gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` và `:latest`, dùng `--cache-from :latest` để tận dụng layer cache.
3. **push** — đẩy image lên Container Registry (`gcr.io`).
4. **deploy** — `gcloud run deploy ai-agent` với image đúng `$COMMIT_SHA` ở `asia-southeast1`: public, 1–10 instance (min 1 để tránh cold start), 512Mi / 1 CPU, timeout 60s, `ENVIRONMENT=production`, `OPENAI_API_KEY` lấy từ **Secret Manager** (không hardcode).

`service.yaml` mô tả cùng service dưới dạng IaC (Knative): autoscale 1–10 instance, mỗi instance tối đa 80 request đồng thời, liveness probe `GET /health`, startup probe `GET /ready`, `AGENT_API_KEY`/`OPENAI_API_KEY` lấy từ Secret Manager qua `secretKeyRef`.


## Part 4: API Security

### Exercise 4.1: API Key authentication
File: `04-api-gateway/develop/app.py`

- **API key được check ở đâu?** Hàm `verify_api_key` (dòng 39-54) đọc header `X-API-Key` qua `APIKeyHeader`. Hàm này được gắn vào endpoint `/ask` bằng `Depends(verify_api_key)` (dòng 70) → mọi request vào `/ask` phải qua bước kiểm tra trước khi tới LLM.
- **Sai key thì sao?** Thiếu header → **401** `"Missing API key"`; có header nhưng sai key → **403** `"Invalid API key."`. Request bị chặn ngay, không gọi LLM (không tốn tiền).
- **Rotate key thế nào?** Key đọc từ biến môi trường `AGENT_API_KEY` (dòng 35) → đặt giá trị mới cho env trên server/platform rồi restart app, không cần sửa code hay commit. (Muốn rotate không downtime thì cho phép cùng lúc 2 key cũ + mới trong thời gian chuyển đổi, rồi bỏ key cũ.)

Chạy: `AGENT_API_KEY=secret-key-123 python app.py` (key demo của lab)
```text
# 1) Không có key
$ curl -i http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# 2) Key sai
$ curl -i http://localhost:8000/ask -X POST -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid API key."}

# 3) Key đúng
$ curl -i http://localhost:8000/ask -X POST -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2: JWT authentication
File: `04-api-gateway/production/auth.py`

**JWT flow:**
1. Client gửi `username`/`password` tới `POST /auth/token` → `authenticate_user` kiểm tra (sai → 401).
2. Server tạo token bằng `create_token` (dòng 35-43): payload gồm `sub` (username), `role`, `iat`, `exp` (hết hạn sau 60 phút), ký bằng `JWT_SECRET` với thuật toán HS256.
3. Client gửi token trong header `Authorization: Bearer <token>` ở mỗi request.
4. `verify_token` (dòng 46-67) kiểm tra chữ ký + hạn → lấy ra `username`, `role` mà **không cần tra database** (stateless). Thiếu token → 401, token hết hạn → 401, token giả/sửa → 403.

### Exercise 4.3: Rate limiting
File: `04-api-gateway/production/rate_limiter.py`

- **Algorithm:** **Sliding window** (log timestamps) — mỗi user có một `deque` lưu thời điểm các request; mỗi lần check thì xoá các mốc cũ hơn 60 giây, nếu còn ≥ limit thì chặn (dòng 35-62).
- **Limit:** user thường (`student`) **10 req/phút**; admin (`teacher`) **100 req/phút** (dòng 86-87).
- **Bypass cho admin:** không bỏ hẳn limit mà dùng limiter riêng rộng hơn, chọn theo `role` trong JWT: `limiter = rate_limiter_admin if role == "admin" else rate_limiter_user` (`app.py` dòng 141).
- **Khi vượt:** trả **429** kèm header `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`.
- *Hạn chế:* state nằm trong RAM của process → restart là mất, chạy nhiều instance thì mỗi instance đếm riêng → production cần lưu trong Redis.

### Exercise 4.2-4.3: Test results (token đã che)
```text
# Lấy token (tài khoản student / demo123)
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username": "student", "password": "demo123"}'
HTTP/1.1 200 OK
content-type: application/json

{"access_token":"eyJ***(đã che)***","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer eyJ***(đã che)***"}

# Sai mật khẩu
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username": "student", "password": "wrong"}'
HTTP/1.1 401 Unauthorized

{"detail":"Invalid credentials"}

# Không có token → 401
$ curl -i http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
content-type: application/json

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Có token → 200
$ curl -i http://localhost:8000/ask -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 200 OK
content-type: application/json

{"question":"Explain JWT","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}

# Gọi liên tục — request 11 trở đi bị chặn
$ for i in {2..12}; do curl -s -o /dev/null -w "Request $i: %{http_code}\n" http://localhost:8000/ask -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"question\": \"Test $i\"}"; done
Request 2: 200
Request 3: 200
Request 4: 200
Request 5: 200
Request 6: 200
Request 7: 200
Request 8: 200
Request 9: 200
Request 10: 200
Request 11: 429
Request 12: 429

# Chi tiết response 429
$ curl -i http://localhost:8000/ask -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question": "Test 13"}'
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795595888
retry-after: 59
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```
→ Đúng 10 request đầu thành công, request thứ 11 bị 429, khớp limit 10 req/phút của user `student`.

### Exercise 4.4: Cost guard implementation

**Vì sao cần cả rate limit và cost guard:** rate limit bảo vệ *tốc độ* (chống spam/DoS, 10 req/phút); cost guard bảo vệ *tiền* — người dùng vẫn có thể gửi chậm nhưng nhiều câu dài suốt ngày làm bill LLM tăng vọt, nên cần trần chi tiêu riêng.

**Bản mẫu `04-api-gateway/production/cost_guard.py`:**
1. **Trước khi gọi LLM** — `check_budget` (dòng 60-91): nếu tổng chi tiêu toàn hệ thống ≥ $10/ngày → **503**; nếu một user ≥ $1/ngày → **402 Payment Required**; dùng ≥ 80% thì log warning.
2. **Sau khi gọi LLM** — `record_usage` (dòng 93-110): cộng dồn input/output tokens, quy ra USD theo giá GPT-4o-mini ($0.15/1M input, $0.60/1M output).
3. **Reset theo ngày:** mỗi `UsageRecord` gắn với `day = %Y-%m-%d`; sang ngày mới `_get_record` tạo record mới (dòng 53-58).
4. **Hạn chế:** lưu trong RAM (dict) → restart mất dữ liệu, nhiều instance đếm riêng → không dùng được khi scale.

**Cách implement theo đề (budget $10/tháng, lưu trong Redis):**
```python
import redis
from datetime import datetime

r = redis.Redis.from_url(os.getenv("REDIS_URL"))
MONTHLY_BUDGET_USD = 10.0

def check_budget(user_id: str, estimated_cost: float) -> bool:
    month_key = datetime.now().strftime("%Y-%m")          # reset đầu tháng nhờ key theo tháng
    key = f"budget:{user_id}:{month_key}"

    current = float(r.get(key) or 0)
    if current + estimated_cost > MONTHLY_BUDGET_USD:
        return False                                     # caller trả HTTP 402

    r.incrbyfloat(key, estimated_cost)                   # cộng dồn atomic trong Redis
    r.expire(key, 32 * 24 * 3600)                        # tự xoá sau 32 ngày
    return True
```
- Key gồm `user_id` + tháng → mỗi tháng tự có bộ đếm mới (reset đầu tháng), `expire` dọn key cũ.
- State nằm trong Redis → mọi instance dùng chung, restart không mất (stateless app).
- Hết budget → endpoint trả **402**, chặn *trước* khi gọi LLM nên không tốn thêm tiền.
- Cải tiến thêm: `get` rồi `incrbyfloat` là 2 bước riêng nên 2 request đồng thời có thể cùng vượt ngưỡng một chút; muốn chặt chẽ thì `incrbyfloat` trước, nếu vượt thì trừ lại và trả 402 (hoặc dùng Lua script).

**Quan sát thêm:** trong response `/ask` của bản mẫu, `"budget_remaining_usd": 1.6e-05` thực ra là **số tiền đã dùng** — `app.py` dòng 160 lấy nhầm `usage.total_cost_usd`. Endpoint `/me/usage` báo đúng:
```text
$ curl http://localhost:8000/me/usage -H "Authorization: Bearer $TOKEN"
{"user_id":"student","date":"2026-11-25","requests":10,"input_tokens":40,"output_tokens":304,"cost_usd":0.000188,"budget_usd":1.0,"budget_remaining_usd":0.999812,"budget_used_pct":0.0}
```


## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks
File: `05-scaling-reliability/develop/app.py` (đã có sẵn implementation)

| | `/health` — liveness | `/ready` — readiness |
|---|---|---|
| Câu hỏi | Process còn sống không? | Có sẵn sàng nhận traffic không? |
| Ai dùng | Platform (Railway/Render/K8s) | Load balancer |
| Non-200 thì sao | Platform **restart** container | LB **ngừng route traffic** vào instance đó (không restart) |
| Code | dòng 104-144: trả uptime, version, check memory (psutil) | dòng 147-168: trả 503 khi `_is_ready=False` (đang khởi động/đang tắt) |

Ví dụ: Redis chết → process vẫn sống nên `/health` = 200 (restart cũng không sửa được Redis), nhưng không phục vụ được nên `/ready` = 503 để LB chuyển traffic sang instance khác.

```text
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":0.8,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:41:30.590975+00:00","checks":{"memory":{"status":"ok","used_percent":77.2}}}
$ curl http://localhost:8000/ready
{"ready":true,"in_flight_requests":1}
```
(`in_flight_requests: 1` chính là request `/ready` đang được xử lý — middleware đếm cả nó.)

### Exercise 5.2: Graceful shutdown
- Middleware `track_requests` (dòng 72-81) đếm số request đang xử lý (`_in_flight_requests`).
- Khi nhận SIGTERM, uvicorn ngừng nhận kết nối mới rồi chạy phần shutdown của `lifespan` (dòng 54-66): đặt `_is_ready = False` (→ `/ready` trả 503, LB ngừng gửi traffic), chờ request đang chạy xong (tối đa 30s), rồi mới thoát. `timeout_graceful_shutdown=30` (dòng 198) là giới hạn chờ của uvicorn.
- SIGTERM bắt được (khác SIGKILL), nên platform gửi SIGTERM trước, chờ một lúc rồi mới SIGKILL.

Test: gửi request mất ~3 giây (mock LLM delay 3s), 0.5 giây sau gửi SIGTERM:
```text
$ python app.py &  PID=$!
$ curl -X POST "http://localhost:8000/ask?question=Long%20task" &
$ kill -TERM $PID

# Request đang chạy dở vẫn hoàn thành:
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
[HTTP 200, thời gian 3.019581s]
[server exit code: 0]

# Gọi lại sau khi tắt:
HTTP 000   (server đã tắt hẳn)
```
Log server:
```text
INFO:     Shutting down
INFO:     127.0.0.1:59804 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-25 15:41:33,733 INFO 🔄 Graceful shutdown initiated...
2026-11-25 15:41:33,733 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [63837]
```
→ `Shutting down` xuất hiện **trước** dòng `POST /ask ... 200 OK`: server nhận SIGTERM nhưng vẫn để request đang chạy trả lời xong (200 sau ~3s) rồi mới thoát với exit code 0 → request của người dùng không bị cắt ngang.

### Exercise 5.3: Stateless design
File: `05-scaling-reliability/production/app.py`

- **Vấn đề:** nếu lưu `conversation_history` trong RAM (dict), mỗi instance có RAM riêng. Khi chạy 3 instance sau load balancer, câu 1 vào instance A (lưu ở RAM của A), câu 2 vào instance B → B không có history → mất ngữ cảnh. Restart/redeploy cũng mất hết.
- **Cách làm đúng:** mọi state lưu trong **Redis** dùng chung: `save_session` dùng `SETEX session:<id>` với TTL 1 giờ, `load_session` đọc lại, `append_to_history` giữ tối đa 20 message (dòng 59-90). Instance nào cũng đọc/ghi được cùng session → có thể scale, restart, thay instance thoải mái.
- Mỗi response có `served_by` = `INSTANCE_ID` để thấy instance nào xử lý.

### Exercise 5.4: Load balancing
Stack: `nginx` (port 8080) → `agent` × 3 → `redis` dùng chung. Nginx `upstream agent_cluster { server agent:8000; }` + Docker DNS trả về IP của cả 3 replica → nginx phân phối round-robin. `proxy_next_upstream error timeout http_503` → instance lỗi/không ready thì tự thử instance khác.

```text
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
$ docker compose -p k5-day14-scaling ps
NAME                       STATUS                            PORTS
k5-day14-scaling-agent-1   Up 4 seconds (health: starting)   8000/tcp
k5-day14-scaling-agent-2   Up 4 seconds (health: starting)   8000/tcp
k5-day14-scaling-agent-3   Up 4 seconds (health: starting)   8000/tcp
k5-day14-scaling-nginx-1   Up 4 seconds                      0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 15 seconds (healthy)           6379/tcp

$ docker compose -p k5-day14-scaling logs agent | grep -E "Starting instance|Storage|POST /chat"
agent-1| INFO:app:Starting instance instance-5325bd
agent-1| INFO:app:Storage: Redis ✅
agent-1| INFO:     172.18.0.6:39600 - "POST /chat HTTP/1.1" 200 OK
agent-1| INFO:     172.18.0.6:39600 - "POST /chat HTTP/1.1" 200 OK
agent-3| INFO:app:Starting instance instance-673209
agent-3| INFO:app:Storage: Redis ✅
agent-3| INFO:     172.18.0.6:49844 - "POST /chat HTTP/1.1" 200 OK
agent-3| INFO:     172.18.0.6:49844 - "POST /chat HTTP/1.1" 200 OK
agent-2| INFO:app:Starting instance instance-1cd587
agent-2| INFO:app:Storage: Redis ✅
agent-2| INFO:     172.18.0.6:38408 - "POST /chat HTTP/1.1" 200 OK
```
→ 5 request được chia cho cả 3 instance (2 / 2 / 1).

**Thử tắt 1 instance** (`docker stop k5-day14-scaling-agent-2` = `instance-1cd587`), rồi gửi 6 request cùng một session mới:
```text
Request 1: instance-673209
Request 2: instance-5325bd
Request 3: instance-673209
Request 4: instance-5325bd
Request 5: instance-673209
Request 6: instance-5325bd
$ curl http://localhost:8080/chat/$SID/history
Total messages: 12
```
→ Traffic tự chuyển sang 2 instance còn lại, không request nào lỗi, history vẫn đủ 12 message (6 hỏi + 6 đáp).

### Exercise 5.5: Test stateless
```text
$ python test_stateless.py
============================================================
Stateless Scaling Demo
============================================================

Session ID: 46d9e572-1aa3-4161-99ca-41db7eb1d321

Request 1: [instance-673209]
  Q: What is Docker?
Request 2: [instance-5325bd]
  Q: Why do we need containers?
Request 3: [instance-1cd587]
  Q: What is Kubernetes?
Request 4: [instance-673209]
  Q: How does load balancing work?
Request 5: [instance-5325bd]
  Q: What is Redis used for?

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-1cd587', 'instance-673209', 'instance-5325bd'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  ...
  [user]: What is Redis used for?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...

✅ Session history preserved across all instances via Redis!
```
**Giải thích:** 5 câu trong cùng một session được 3 instance khác nhau trả lời theo vòng (round-robin), nhưng history vẫn đủ 10 message (5 user + 5 assistant) theo đúng thứ tự. Lý do: không instance nào giữ state trong RAM — mỗi request đọc history từ Redis, thêm message mới rồi ghi lại vào Redis. Nếu lưu trong RAM, mỗi instance chỉ thấy 1–2 câu của mình và history sẽ bị đứt đoạn.


## Part 6: Final Project

### Output check_production_ready.py (📋 Checklist Deliverable)
Chạy đầy đủ (có Docker) trong `06-lab-complete/`: `python check_production_ready.py`
```text
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
```

### Tóm tắt cách làm
| File | Làm gì |
|---|---|
| `app/config.py` | Mọi cấu hình đọc từ env (`PORT`, `ENVIRONMENT`, `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`), không hardcode secret; `.env.example` liệt kê đủ biến |
| `app/main.py` | `JsonFormatter` + middleware → mỗi request 1 dòng log JSON (không log key/câu hỏi); `/health` luôn 200; `/ready` 503 khi Redis không ping được; `/ask` = auth → rate limit → budget → LLM → ghi chi phí; `RedisError` → 503 gọn; `lifespan` log startup/shutdown và đóng Redis |
| `app/auth.py` | `APIKeyHeader("X-API-Key")`, thiếu/sai/server chưa đặt key → **401**; so sánh bằng `secrets.compare_digest` |
| `app/redis_client.py` | `redis.from_url(...)` không kết nối lúc import (app vẫn khởi động khi Redis chết), timeout 1s; `redis_healthy()` = ping |
| `app/rate_limiter.py` | Sliding window bằng Redis sorted set (ZREMRANGEBYSCORE → ZADD → ZCARD → EXPIRE trong 1 transaction), key là hash của API key; vượt → **429** + `Retry-After`; restart vẫn còn state |
| `app/cost_guard.py` | Cộng dồn chi phí (token ước lượng ~4 ký tự/token × giá gpt-4o-mini) vào key Redis `cost:daily:<YYYY-MM-DD>`; vượt `DAILY_BUDGET_USD` → **402** trước khi gọi LLM |
| `Dockerfile` | Multi-stage `python:3.11-slim`, không cần apt, user non-root `app`, `HEALTHCHECK /health`, `CMD sh -c "exec uvicorn ... --port ${PORT:-8000} --workers 2 --timeout-graceful-shutdown 8"` → uvicorn là PID 1; image **262 MB**, `docker stop` 0.8s exit 0 |
| `.dockerignore` | Loại `.env*` (giữ `.env.example`), `__pycache__`, `venv/.venv`, `.git`, `*.md`, Part 7, script chấm |
| `docker-compose.yml` | `agent` (build `.`, `REDIS_URL=redis://redis:6379/0`, `.env` optional, `depends_on` redis healthy) + `redis:7-alpine` có healthcheck |
| `railway.toml` / `render.yaml` | Railway: builder `DOCKERFILE`, `healthcheckPath = "/health"`. Render: web docker + Key Value Redis, `AGENT_API_KEY` dùng `sync: false` |

## Part 7: Benchmark & Observability
Số liệu benchmark chi tiết: [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md).

### Exercise 7.1: Đọc metrics của agent
Chạy trong `06-lab-complete/benchmark-observability/develop/`: v1 ở port 8001, v2 ở port 8002.
```text
$ curl -s -X POST http://localhost:8002/ask -H "Content-Type: application/json" -d '{"question": "Prometheus thu thập metrics như thế nào?"}'
{"answer":"Prometheus pull metrics bằng cách scrape endpoint /metrics theo chu kỳ. ...","model":"mock-llm-small","agent_version":"v2","usage":{"input_tokens":91,"output_tokens":55,"cost_usd":4.665e-05},"llm_latency_ms":154.3,"request_id":"4eda58da3d00"}

$ curl -s http://localhost:8002/metrics | grep -v "^#"   (trích)
http_requests_total{method="POST",route="/ask",status="200"} 1.0
http_request_duration_seconds_bucket{le="0.2",method="POST",route="/ask"} 1.0
http_request_duration_seconds_count{method="POST",route="/ask"} 1.0
http_request_duration_seconds_sum{method="POST",route="/ask"} 0.17988687499018852
agent_in_flight_requests 0.0
llm_tokens_total{model="mock-llm-small",type="input"} 91.0
llm_tokens_total{model="mock-llm-small",type="output"} 55.0
llm_cost_usd_total{model="mock-llm-small"} 4.6649999999999996e-05
agent_info{model="mock-llm-small",version="v2"} 1.0
```

**1. Ví dụ mỗi loại metric:**
| Loại | Ví dụ trong output | Đặc điểm |
|---|---|---|
| Counter | `http_requests_total{method="POST",route="/ask",status="200"} 1.0`, `llm_tokens_total{type="input"} 91.0`, `llm_cost_usd_total` | Chỉ tăng (đếm request, token, cost); xem tốc độ bằng `rate()` |
| Gauge | `agent_in_flight_requests 0.0`, `agent_info{version="v2"} 1.0` | Lên xuống được — giá trị tại thời điểm scrape (số request đang xử lý) |
| Histogram | `http_request_duration_seconds_bucket{le="0.2",route="/ask"} 1.0` + `_count` + `_sum` | Đếm số quan sát rơi vào từng bucket latency → tính p95/p99 bằng `histogram_quantile`, avg = `_sum / _count` |

**2. Nếu label `route` dùng URL thật (`request.url.path`):** mỗi giá trị label khác nhau là một time series mới. Bot quét gọi hàng nghìn URL lạ (`/wp-admin`, `/.env`, `/a1b2c3`...) → mỗi URL tạo thêm ~15 series (1 counter + 12 bucket histogram + `_count` + `_sum`), không bao giờ bị xoá → **cardinality bùng nổ**: RAM của agent và Prometheus tăng không giới hạn, query chậm, có thể OOM — kẻ tấn công còn lợi dụng được để làm sập hệ thống giám sát. Dùng route template (`/ask`) và gán `unmatched` cho URL không khớp thì số series cố định và nhỏ.

**Nhiệm vụ — thêm metric `agent_question_length_chars`** (`develop/app.py`):
```python
QUESTION_LENGTH = Histogram(
    "agent_question_length_chars", "Độ dài câu hỏi (ký tự)",
    buckets=(20, 50, 100, 200, 500, 1000, 2000),
)
# trong ask(), trước khi gọi LLM:
QUESTION_LENGTH.observe(len(body.question))
```
Dùng Histogram với bucket cố định, không dùng label `length=...` vì độ dài có vô số giá trị (cardinality). Kiểm tra sau khi restart v2:
```text
agent_question_length_chars_bucket{le="20.0"} 0.0
agent_question_length_chars_bucket{le="50.0"} 1.0
...
agent_question_length_chars_count 1.0
agent_question_length_chars_sum 40.0
```

## AI log
| # | Hỏi AI gì | AI trả lời / gợi ý gì | Mình tự sửa & tự kiểm tra thế nào |
|---|-----------|------------------------|------------------------------------|
| 1 | Nhờ Claude Code chỉ ra các anti-pattern trong `01-localhost-vs-production/develop/app.py` (Ex 1.1) | Danh sách 9 vấn đề kèm số dòng và lý do | Tự mở file đối chiếu từng dòng, đọc lại giải thích và viết lại theo cách hiểu của mình |
| 2 | Nhờ Claude Code chạy bản develop và production của Part 1, so sánh 2 file `app.py` (Ex 1.2, 1.3) | Output curl thật từ máy mình + bảng so sánh | Đối chiếu output với log server; tự đọc `production/app.py` và `config.py` để kiểm tra từng dòng trong bảng |
| 3 | Nhờ Claude Code giải thích Dockerfile develop/production, build image, chạy docker compose (Ex 2.1–2.4); hỏi nguyên nhân build lỗi `401 VG-AuthenticationRequired` | Giải thích 4 câu 2.1, multi-stage, sơ đồ service; chẩn đoán proxy trường chặn `http://` của apt | Tự đọc lại 2 Dockerfile và `docker-compose.yml`; đổi sang Wi-Fi khác rồi build lại thành công; số MB lấy từ `docker images` trên máy mình |
| 4 | Nhờ Claude Code giải thích API key, JWT, rate limiter, cost guard và chạy test Part 4 (Ex 4.1–4.4) | Output 401/403/200/429 thật, giải thích thuật toán sliding window, cách làm cost guard bằng Redis | Tự đọc `auth.py`, `rate_limiter.py`, `cost_guard.py`; kiểm tra request 11 bị 429 khớp limit 10/phút; tự che token trước khi dán |
| 5 | Nhờ Claude Code giải thích health/ready, graceful shutdown, stateless và chạy test Part 5 (Ex 5.1–5.5) | Output thật: request vẫn 200 khi gửi SIGTERM; 3 instance cùng phục vụ 1 session, history đủ 10 message; tắt 1 instance vẫn không lỗi | Tự đọc log server để thấy thứ tự `Shutting down` → `200 OK`; đối chiếu `served_by` với log `docker compose logs agent` |
| 6 | Nhờ Claude Code hướng dẫn từng bước Part 6: đọc script chấm, đề xuất code cho config, log JSON, /health, /ready, auth, rate limiter Redis, cost guard, lifespan, Dockerfile, compose, railway.toml/render.yaml | Code từng file kèm giải thích; sau mỗi bước chạy thử bằng curl và `check_production_ready.py` | Đọc và duyệt từng đoạn trước khi sửa; tự kiểm tra 401/429/402/503 bằng curl, restart agent vẫn 429; chạy `check_production_ready.py` đầy đủ (không tham số) → PASS 12/12; không sửa script chấm |
| 7 | Nhờ Claude Code hướng dẫn deploy Railway (CP6), viết `DEPLOYMENT.md`, so sánh `railway.toml`/`render.yaml`, tóm tắt pipeline Cloud Run (Ex 3.3) | Các lệnh Railway CLI (init, add redis, add agent + variables, up, domain), bảng so sánh, mô tả 4 bước pipeline | Tự đăng nhập Railway; tự chạy 4 lệnh tự kiểm CP6 (200/200/401/200) và chụp ảnh; key sinh ngẫu nhiên, chỉ nằm trên Railway; tự đọc `cloudbuild.yaml`, `service.yaml` để đối chiếu |
| 8 | Nhờ Claude Code chạy Part 7 Bước 1 (Ex 7.1–7.3): đọc metrics, thêm metric `agent_question_length_chars`, load test 4 mức concurrency + 3 mức `MOCK_SLOW_RATE`, eval v1/v2, đề xuất tài liệu bổ sung `KNOWLEDGE_BASE`, viết job CI | File JSON trong `develop/reports/`, giải thích kết quả, 2 entry KB mới (JWT, HPA), `.github/workflows/eval.yml` | Duyệt 2 entry KB trước khi sửa (không sửa `golden_dataset.jsonl`); mô phỏng retrieval cho 23 câu để chắc không regression; mọi số trong `BENCHMARK_REPORT.md` lấy bằng script từ file JSON; chạy thử các bước của job CI trên máy → PASS |
