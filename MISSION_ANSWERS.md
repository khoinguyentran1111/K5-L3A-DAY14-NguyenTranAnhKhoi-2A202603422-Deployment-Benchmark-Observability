# Day 14 Lab — Mission Answers

> Mọi output dưới đây là output thật từ các lệnh đã chạy trên máy làm bài (Windows 11 + Docker Desktop 29.9.3,
> Python 3.11 trong venv; phần cần SIGTERM thật chạy trong WSL2 Ubuntu 22.04). Token / API key đã được che (`***`).
> Ngày chạy: 2026-11-25.

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

| # | Anti-pattern | Dòng | Hậu quả |
|---|---|---|---|
| 1 | Hard-code secret: `OPENAI_API_KEY = "sk-hardcoded-..."`, `DATABASE_URL = "postgresql://admin:password123@..."` | 17–18 | Push lên GitHub là lộ key + mật khẩu DB; muốn đổi key phải sửa code và deploy lại |
| 2 | **Log ra secret**: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | 34 | Key nằm trong log của mọi hệ thống thu log. Đã thấy thật khi chạy: `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this` |
| 3 | `print()` thay cho logging có cấu trúc, không có level, không JSON | 33–38 | Không lọc/tìm được trên log aggregator, không tắt được debug log ở production |
| 4 | Config cứng trong code: `DEBUG = True`, `MAX_TOKENS = 500` | 21–22 | Không đổi được giữa dev/staging/prod nếu không sửa code (vi phạm 12-Factor "Config") |
| 5 | Không có `/health` (đã thử: `GET /health -> 404`) | — | Platform không biết process còn sống hay treo để restart |
| 6 | Bind `host="localhost"` | 51 | Trong container chỉ nghe loopback của container → từ ngoài không truy cập được |
| 7 | Port cứng `port=8000` | 52 | Railway/Render cấp port qua biến `PORT` → app nghe sai port, healthcheck fail |
| 8 | `reload=True` | 53 | File watcher chạy ở production: tốn tài nguyên, tự restart khi file đổi |
| 9 | Không xử lý shutdown / không có readiness | — | Deploy mới hoặc scale-in cắt ngang request đang chạy |
| 10 | `/ask` nhận `question` qua query string, không validate | 31 | Câu hỏi dài/bí mật nằm trong URL → bị log ở proxy; gửi JSON thì 422 (đã thấy) |

### Exercise 1.2: Chạy bản develop

```text
$ curl -s -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}

$ curl -s -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}' | head -1
HTTP/1.1 422 Unprocessable Entity

$ curl -s -o /dev/null -w "GET /health -> %{http_code}\n" http://localhost:8000/health
GET /health -> 404
```

Log server (thấy rõ secret bị in ra):

```text
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.
```

**Quan sát:** chạy được, nhưng không production-ready: lộ secret, không health check, chỉ nghe `localhost`.

### Exercise 1.3: So sánh với bản production

Chạy `production/app.py` (đã `cp .env.example .env`, file `.env` nằm trong `.gitignore`):

```text
$ curl -s -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.8,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T09:09:23.916463+00:00"}

$ curl -s -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true}

$ curl -s -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","model":"gpt-4o-mini"}
```

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hard-code trong code (`DEBUG=True`, key, DB URL) | `config.py` đọc env (`os.getenv`), có `validate()` fail-fast khi thiếu `AGENT_API_KEY` ở production | Cùng một image chạy mọi môi trường; đổi config không cần build lại; secret không vào git |
| Secrets | Ghi thẳng trong code và **in ra log** | Đọc từ env, không log secret (chỉ log `question_length`) | Lộ secret = mất tiền / mất dữ liệu; log được nhiều người/hệ thống đọc |
| Health check | Không có (`/health` → 404) | `/health` (liveness) + `/ready` (readiness) | Platform/LB biết khi nào restart, khi nào ngừng route traffic |
| Logging | `print()` | `logging` với format JSON | Log aggregator (Loki, Datadog...) parse/lọc được theo field |
| Shutdown | Đột ngột | `lifespan` shutdown + handler SIGTERM, uvicorn chờ request xong | Không cắt ngang request khi deploy / scale-in |
| Host / Port | `localhost:8000` cố định | `HOST=0.0.0.0`, `PORT` từ env | Chạy được trong container và trên Railway/Render (port do platform cấp) |
| Reload | `reload=True` luôn bật | Chỉ bật khi `DEBUG=true` | Không chạy file watcher ở production |
| CORS | Không cấu hình | `ALLOWED_ORIGINS` từ env | Giới hạn origin được gọi API từ trình duyệt |

**Phát hiện thêm khi chạy thật:** log JSON của bản production *không hiện ra* (log server chỉ có `WARNING:root:OPENAI_API_KEY not set` và access log của uvicorn).
Nguyên nhân: `config.py` gọi `logging.warning(...)` **lúc import**, trước khi `app.py` chạy `logging.basicConfig(...)`. Lần gọi đầu tiên đã tự cấu hình root logger (level WARNING), nên `basicConfig` sau đó không có tác dụng và mọi `logger.info(json.dumps(...))` bị nuốt. Ngoài ra format `'{"msg":"%(message)s"}'` sẽ ra JSON hỏng nếu message chứa dấu `"`. Ở Part 6 mình tự viết `JsonFormatter` dùng `json.dumps` cho cả record để tránh cả hai lỗi này.

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11`, bản Python đầy đủ trên Debian (có compiler, header, nhiều tool), nên rất nặng.
2. **Working directory:** `/app` (`WORKDIR /app`), mọi lệnh `COPY`/`RUN`/`CMD` sau đó chạy tương đối từ đây.
3. **Vì sao `COPY requirements.txt` trước:** Docker cache theo layer. Layer `pip install` chỉ build lại khi `requirements.txt` đổi. Nếu `COPY . .` trước thì mỗi lần sửa 1 dòng code, cache của bước cài dependencies bị vô hiệu và phải cài lại toàn bộ (chậm hàng phút).
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh/tham số **mặc định**, bị thay thế hoàn toàn khi `docker run image <lệnh khác>`. `ENTRYPOINT` là executable **cố định** của container, tham số của `docker run` được nối thêm vào sau nó (muốn đổi phải `--entrypoint`). Kết hợp phổ biến: `ENTRYPOINT ["uvicorn"]` + `CMD ["app:app", "--port", "8000"]`. Cả hai nên viết dạng exec (JSON array) để process là PID 1 và nhận được SIGTERM.

### Exercise 2.2: Build và chạy

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -p 8000:8000 my-agent:develop
$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker?"
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ curl -s http://localhost:8000/health
{"status":"ok","uptime_seconds":0.3,"container":true}

$ docker exec p2-develop id
uid=0(root) gid=0(root) groups=0(root)        ← bản develop chạy bằng root
```

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`)

- **Stage 1 (builder):** `python:3.11-slim` + `apt-get install gcc libpq-dev`, rồi `pip install --user -r requirements.txt` vào `/root/.local`. Stage này có compiler và cache apt, **không** được deploy.
- **Stage 2 (runtime):** `python:3.11-slim` sạch, tạo user `appuser` (non-root), chỉ `COPY --from=builder /root/.local` + `main.py` + `utils/`, có `HEALTHCHECK`, chạy `uvicorn --workers 2`.
- **Vì sao nhỏ hơn:** image cuối không chứa gcc, header, cache apt/pip, và base là `slim` thay vì bản đầy đủ. `docker history my-agent:advanced` cho thấy toàn bộ dependencies chỉ là 1 layer 40.8 MB.

Kết quả đo:

```text
$ docker images
REPOSITORY:TAG        SIZE
my-agent:advanced     240MB
my-agent:develop      1.67GB

$ docker image inspect --format '{{.Size}}'
my-agent:develop  1667792138 bytes
my-agent:advanced  239811259 bytes
```

- Develop: **1667.8 MB**
- Production: **239.8 MB**
- Chênh lệch: nhỏ hơn **85.6%** (develop to gấp 6.95 lần)

Kiểm tra container advanced:

```text
$ curl -i -X POST http://localhost:8001/ask -H "Content-Type: application/json" -d '{"question":"What is Docker?"}'
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
$ docker exec p2-advanced id
uid=999(appuser) gid=999(appuser) groups=999(appuser)   ← non-root
```

Lỗi nhỏ quan sát được ở log của image advanced: `{"time":"...","level":"INFO","msg":"{"event": "request", "q_len": 15}"}` **không phải JSON hợp lệ** (chuỗi JSON lồng vào `"%(message)s"` mà không escape dấu nháy).

### Exercise 2.4: Docker Compose stack

Chạy: `touch .env.local && docker compose -p k5-day14-docker up -d --build` trong `02-docker/production/`.

```text
                        ┌────────────────── network "internal" (bridge) ──────────────────┐
  Client ── :80/:443 ──▶│ nginx (nginx:alpine)                                             │
  (host)                │   reverse proxy + rate limit 10 r/s/IP + security headers        │
                        │        │ proxy_pass http://agent_backend (agent:8000)           │
                        │        ▼                                                          │
                        │ agent (build 02-docker/production/Dockerfile, target runtime)    │
                        │   ├── redis://redis:6379/0   → redis:7-alpine (cache, session)   │
                        │   └── http://qdrant:6333     → qdrant/qdrant:v1.9.0 (vector DB)  │
                        └───────────────────────────────────────────────────────────────────┘
```

- **Services được start:** `redis`, `qdrant` (start trước, có healthcheck) → `agent` (`depends_on: condition: service_healthy`) → `nginx`.
- **Giao tiếp:** cùng network bridge `internal`, gọi nhau bằng **tên service** qua DNS nội bộ của Docker (`agent:8000`, `redis:6379`, `qdrant:6333`). Chỉ nginx publish port ra host (80, 443); agent/redis/qdrant không mở port ra ngoài.

```text
$ docker compose -p k5-day14-docker ps
NAME                       STATUS                    PORTS
k5-day14-docker-agent-1    Up 8 seconds (healthy)    8000/tcp
k5-day14-docker-nginx-1    Up 8 seconds              0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
k5-day14-docker-qdrant-1   Up 19 seconds (healthy)   6333-6334/tcp
k5-day14-docker-redis-1    Up 19 seconds (healthy)   6379/tcp

$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
{"status":"ok","uptime_seconds":7.1,"version":"2.0.0","timestamp":"2026-11-25T09:14:17.543253"}

$ curl -i http://localhost/ask -X POST -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}

$ docker network inspect k5-day14-docker_internal
k5-day14-docker-qdrant-1 172.21.0.2/16
k5-day14-docker-redis-1  172.21.0.3/16
k5-day14-docker-agent-1  172.21.0.4/16
k5-day14-docker-nginx-1  172.21.0.5/16
```

Header `Server: nginx` + các security header chứng tỏ request đi qua Nginx rồi mới tới agent.

---

## Part 3: Cloud Deployment

> Deploy chính agent Part 6 (`06-lab-complete/`), theo CHECKPOINTS CP6.

### Exercise 3.1 / 3.2: Nền tảng chính

- **Nền tảng:** Railway (config: [`06-lab-complete/railway.toml`](06-lab-complete/railway.toml))
- **URL:** `<<ĐIỀN SAU KHI DEPLOY>>`, chi tiết trong [DEPLOYMENT.md](DEPLOYMENT.md)
- **Ảnh:** [screenshots/dashboard.png](screenshots/dashboard.png), [screenshots/running.png](screenshots/running.png), [screenshots/test.png](screenshots/test.png)

### So sánh `railway.toml` và `render.yaml` (nền tảng còn lại)

| | `railway.toml` | `render.yaml` |
|---|---|---|
| Định dạng / vai trò | TOML, config-as-code **cho một service** (build + deploy) | YAML Blueprint, mô tả **cả hạ tầng**: nhiều service, database, Key Value (Redis), env group |
| Build | `[build] builder = "DOCKERFILE"`, `dockerfilePath` | `runtime: docker`, `dockerfilePath`, `dockerContext` (tính từ gốc repo, nên trỏ `./06-lab-complete/...`) |
| Start command | Không cần: dùng `CMD` trong Dockerfile, nghe `${PORT}` do Railway cấp | Như Railway, dùng `CMD` của image |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout` | `healthCheckPath: /health` |
| Restart | `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3` | Render tự restart, không cấu hình trong file |
| Redis | Không khai báo trong file: thêm plugin Redis trong project, đặt `REDIS_URL=${{Redis.REDIS_URL}}` ở biến của service | Khai báo ngay trong file: `type: keyvalue` + `fromService: { type: keyvalue, property: connectionString }` → tự nối `REDIS_URL` |
| Secret | Không ghi trong file, đặt bằng `railway variables set AGENT_API_KEY=...` | `sync: false` (nhập tay trên dashboard) hoặc `generateValue: true` (Render tự sinh), không ghi giá trị |
| Region / plan | Chọn trên dashboard | Ghi trong file: `region: singapore`, `plan: free` |

**Vì sao khác nhau:** Railway xem mỗi service là một đơn vị, file chỉ lo build/deploy, phần còn lại (DB, biến) quản lý trên dashboard/CLI. Render Blueprint là Infrastructure-as-Code đầy đủ: một file dựng lại toàn bộ stack (web + Redis + nối biến) khi tạo Blueprint, nên phải mô tả cả quan hệ giữa các service.

### Exercise 3.3: Pipeline CI/CD Cloud Run (`cloudbuild.yaml` + `service.yaml`)

1. **test:** container `python:3.11-slim` cài `requirements.txt` + pytest, chạy `pytest tests/`. Test fail thì pipeline dừng, không build.
2. **build:** `docker build` image, gắn 2 tag `gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` và `:latest`, dùng `--cache-from :latest` để tận dụng layer cache.
3. **push:** đẩy cả 2 tag lên Container Registry.
4. **deploy:** `gcloud run deploy` image theo **commit SHA** (bất biến, rollback được) lên `asia-southeast1`, min 1 instance (tránh cold start), max 10, 512Mi/1 CPU, timeout 60s; env `ENVIRONMENT=production`, secret `OPENAI_API_KEY` lấy từ Secret Manager.
5. `service.yaml` mô tả cùng service dạng Knative (IaC, `gcloud run services replace`): concurrency 80 request/instance, autoscale 1–10, `AGENT_API_KEY`/`OPENAI_API_KEY` từ Secret Manager, `livenessProbe` → `/health`, `startupProbe` → `/ready`.

---

## Part 4: API Security

### Exercise 4.1: API key (`04-api-gateway/develop`, chạy `AGENT_API_KEY=secret-key-123 python app.py`)

- **Key được check ở đâu:** dependency `verify_api_key()` (dòng 39–54), dùng `APIKeyHeader(name="X-API-Key", auto_error=False)`, gắn vào `/ask` bằng `Depends(verify_api_key)`.
- **Sai key:** thiếu key → **401**; có key nhưng sai → **403** `Invalid API key.`
- **Rotate key:** key đọc từ env `AGENT_API_KEY` nên đổi biến môi trường rồi restart/redeploy. Muốn rotate không downtime thì cho phép tạm thời 2 key (cũ + mới), chuyển client sang key mới rồi gỡ key cũ.

```text
$ curl -s -i http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -s -i http://localhost:8000/ask -X POST -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -s -i http://localhost:8000/ask -X POST -H "X-API-Key: ***" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2: JWT (`04-api-gateway/production`)

Flow: `POST /auth/token` (username/password) → `create_token()` ký HS256 payload `{sub, role, iat, exp(+60')}` bằng `JWT_SECRET` → client gửi `Authorization: Bearer <token>` → `verify_token()` kiểm chữ ký + hạn, lấy `username`/`role` mà **không tra DB**.

```text
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username": "student", "password": "demo123"}'
HTTP/1.1 200 OK
x-content-type-options: nosniff
x-frame-options: DENY
{"access_token":"eyJ***MASKED***","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer eyJ***MASKED***"}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer ***" -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock). ...","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}
```

### Exercise 4.3: Rate limiting

- **Thuật toán:** sliding window log, mỗi user một `deque` timestamp; xoá timestamp cũ hơn 60s rồi đếm (`rate_limiter.py`).
- **Giới hạn:** user `10 req/phút` (`rate_limiter_user`), admin `100 req/phút` (`rate_limiter_admin`).
- **Bypass cho admin:** không bypass hẳn mà dùng limiter khác theo `role` trong JWT (`limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`). Tài khoản `teacher` có role admin.
- **Hạn chế:** state nằm trong RAM của process. Chạy 2 worker / nhiều instance thì mỗi nơi đếm riêng (giới hạn thật thành 10 × số process), restart là mất. Part 6 chuyển state này sang Redis.

Vòng lặp 20 request với token `student` (request "Explain JWT" ở trên là request số 1 trong cửa sổ):

```text
[1] HTTP/1.1 200 OK  {...,"usage":{"requests_remaining":8,...}}
[2] HTTP/1.1 200 OK  {...,"usage":{"requests_remaining":7,...}}
...
[9] HTTP/1.1 200 OK  {...,"usage":{"requests_remaining":0,...}}
[10] HTTP/1.1 429 Too Many Requests  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":57}}
[11] HTTP/1.1 429 Too Many Requests  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":57}}
...
[20] HTTP/1.1 429 Too Many Requests  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":55}}

$ curl -i ... (một response 429 đầy đủ)
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795597882
retry-after: 54
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":54}}
```

10 request được phục vụ (1 + 9) rồi bị chặn 429, có `Retry-After`. Quan sát thêm: field `budget_remaining_usd` trong response thực ra trả `usage.total_cost_usd` (số **đã tiêu**, tăng dần 2.1e-05 → 0.000188), đặt tên sai; `/me/usage` mới cho số còn lại đúng (`budget_remaining_usd: 0.999812`).

### Exercise 4.4: Cost guard

Cách làm trong agent Part 6 ([`06-lab-complete/app/cost_guard.py`](06-lab-complete/app/cost_guard.py)):

1. **Trước khi gọi LLM:** `check_budget()` đọc 2 key Redis `cost:daily:YYYY-MM-DD` và `cost:monthly:YYYY-MM` (UTC) bằng một `MGET`; nếu `daily ≥ DAILY_BUDGET_USD` hoặc `monthly ≥ MONTHLY_BUDGET_USD` thì trả **402 Payment Required**, không gọi LLM.
2. **Sau khi gọi LLM:** `record_cost()` tính `cost = in_tokens/1000 × $0.00015 + out_tokens/1000 × $0.0006` rồi `INCRBYFLOAT` vào cả 2 key trong một transaction (`MULTI`), đặt `EXPIRE` 2 ngày / 32 ngày. Key theo ngày/tháng nên **tự reset** sang chu kỳ mới, không cần cron.
3. State ở Redis nên mọi worker/instance cộng chung một con số (khác bản in-memory của `04-api-gateway`), restart không mất.
4. Ngân sách đọc từ env nên đổi không cần build lại. Kiểm bằng script chấm với `DAILY_BUDGET_USD=0.000001` → `402 ở request thứ 1` (xem Part 6).

**Rate limit vs cost guard:** rate limit bảo vệ **tốc độ** (một client không spam được, chống abuse/DoS), cost guard bảo vệ **tiền** (tổng chi theo ngày/tháng). Cần cả hai: 10 req/phút hợp lệ vẫn có thể đốt $$$ nếu mỗi request dùng prompt rất dài hoặc model đắt, ngược lại budget lớn vẫn cần chặn một client gọi dồn dập.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks (`05-scaling-reliability/develop`)

- `/health` (**liveness**): "process còn sống không?" Trả 200 + uptime + check memory (psutil). Fail → platform **restart** container.
- `/ready` (**readiness**): "có nên nhận traffic không?" Trả 503 khi đang khởi động/đang tắt/dependency chưa sẵn sàng. Fail → LB **ngừng route** tới instance nhưng không restart.
- Phải tách 2 endpoint: nếu Redis chết mà `/health` cũng fail thì platform restart liên tục mọi instance (restart không sửa được Redis) → sập dây chuyền. Vì vậy ở Part 6 `/health` luôn 200, còn `/ready` trả 503 khi mất Redis.

```text
$ curl -i http://localhost:8011/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.5,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T09:10:48.129760+00:00","checks":{"memory":{"status":"ok","used_percent":16.5}}}

$ curl -i http://localhost:8011/ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}
```

### Exercise 5.2: Graceful shutdown (chạy trong WSL2 để gửi được SIGTERM thật)

```text
$ python app.py &  PID=$!
$ curl -X POST "http://localhost:8011/ask?question=Long%20task" &
$ kill -TERM $PID
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
[in-flight request] HTTP 200 after 3.031283s
[server] exit code: 0

--- server log ---
INFO:     Shutting down
INFO:     127.0.0.1:35358 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-25 16:10:51,278 INFO 🔄 Graceful shutdown initiated...
2026-11-25 16:10:51,278 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [438]
2026-11-25 16:10:51,278 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Kết quả:** request đang chạy vẫn hoàn thành (200), process thoát với exit code 0. Thứ tự: uvicorn ngừng nhận kết nối mới → chờ request in-flight → lifespan shutdown → thoát.
**Quan sát:** dòng `Received signal 15` của handler tự viết in ra **sau cùng**. `uvicorn.run()` thay handler SIGTERM của app bằng handler riêng trong lúc serve, rồi khôi phục và phát lại tín hiệu sau khi tắt xong. Handler của app không phải thứ tạo ra graceful shutdown, uvicorn mới là. Nếu tự đăng ký handler mà không gọi lại handler của uvicorn thì process sẽ không bao giờ tắt (CODE_LAB Step 7).

### Exercise 5.3: Stateless design (`05-scaling-reliability/production/app.py`)

Session/conversation history lưu trong Redis (`session:<id>`, `SETEX` TTL 1h, giữ 20 message gần nhất), không lưu trong dict của process. Lý do: scale ra nhiều instance thì mỗi instance có RAM riêng; request 2 của cùng user có thể rơi vào instance khác và mất history. Ngoài ra restart/deploy là mất toàn bộ state trong RAM. (Code vẫn có fallback in-memory khi không kết nối được Redis, chỉ dùng cho dev.)

### Exercise 5.4: Load balancing (`docker compose -p k5-day14-scaling up -d --build --scale agent=3`)

```text
NAME                       STATUS                       PORTS
k5-day14-scaling-agent-1   Up (health: starting)        8000/tcp
k5-day14-scaling-agent-2   Up (health: starting)        8000/tcp
k5-day14-scaling-agent-3   Up (health: starting)        8000/tcp
k5-day14-scaling-nginx-1   Up                           0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up (healthy)                 6379/tcp

$ for i in 1..10: curl -X POST http://localhost:8080/chat ...   (header X-Served-By)
[1] X-Served-By: 172.21.0.3:8000
[2] X-Served-By: 172.21.0.4:8000
[3] X-Served-By: 172.21.0.5:8000
[4] X-Served-By: 172.21.0.3:8000
[5] X-Served-By: 172.21.0.4:8000
[6] X-Served-By: 172.21.0.5:8000
[7] X-Served-By: 172.21.0.3:8000
[8] X-Served-By: 172.21.0.4:8000
[9] X-Served-By: 172.21.0.5:8000
[10] X-Served-By: 172.21.0.3:8000

$ docker compose logs agent | grep "POST /chat" | đếm theo instance
      5 agent-1
      6 agent-2
      5 agent-3
```

Nginx chia **round-robin** đều cho 3 instance (DNS `agent` của Docker trả về 3 IP).

**Thử tắt 1 instance** (`docker stop k5-day14-scaling-agent-2`) rồi gửi tiếp vào cùng session:

```text
[turn 2] HTTP/1.1 200 OK | X-Served-By: 172.21.0.4:8000, 172.21.0.5:8000 | "served_by":"instance-27f02c"
[turn 3] HTTP/1.1 200 OK | X-Served-By: 172.21.0.3:8000 | "served_by":"instance-e6750e"
[turn 4] HTTP/1.1 200 OK | X-Served-By: 172.21.0.5:8000 | "served_by":"instance-27f02c"
[turn 5] HTTP/1.1 200 OK | X-Served-By: 172.21.0.3:8000 | "served_by":"instance-e6750e"
[turn 6] HTTP/1.1 200 OK | X-Served-By: 172.21.0.5:8000 | "served_by":"instance-27f02c"
[turn 7] HTTP/1.1 200 OK | X-Served-By: 172.21.0.3:8000 | "served_by":"instance-e6750e"
$ GET /chat/<session>/history  → messages: 14
```

Không request nào lỗi. Request đầu tiên trúng instance đã chết (`172.21.0.4`), Nginx tự thử lại instance kế tiếp nhờ `proxy_next_upstream error timeout http_503` (header có **2 địa chỉ**), sau đó chỉ còn 2 instance sống luân phiên. History đủ 14 message (7 lượt hỏi + 7 trả lời).

### Exercise 5.5: `python test_stateless.py`

```text
Session ID: bce749ba-dd8d-4b58-93e9-e2347af5c529

Request 1: [instance-b465a1]   Q: What is Docker?
Request 2: [instance-27f02c]   Q: Why do we need containers?
Request 3: [instance-e6750e]   Q: What is Kubernetes?
Request 4: [instance-b465a1]   Q: How does load balancing work?
Request 5: [instance-27f02c]   Q: What is Redis used for?
------------------------------------------------------------
Total requests: 5
Instances used: {'instance-27f02c', 'instance-b465a1', 'instance-e6750e'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  ...
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 câu của **cùng một session** được 3 instance khác nhau xử lý (round-robin), nhưng history đọc lại vẫn đủ 10 message theo đúng thứ tự, vì mỗi instance đọc/ghi `session:<id>` trong Redis chứ không giữ trong RAM. Nếu lưu dict trong memory, mỗi instance chỉ thấy phần history của chính nó (khoảng 1/3). Script không tự tắt instance nào; thí nghiệm tắt instance ở 5.4 bổ sung phần đó.
**Lỗi nhỏ phát hiện:** field `turn` trong response bị lệch +1 (lượt 2 trả `"turn":3`), vì code đếm history **sau khi** đã append câu hỏi hiện tại rồi còn `+ 1`.

Dọn dẹp: `docker compose -p k5-day14-scaling down`.

---

## Part 6: Final Project, kết quả `check_production_ready.py`

Chạy trong `06-lab-complete/` bằng Python 3.11 **trong WSL2** (`os.name == posix`, gửi được SIGTERM thật), Docker Desktop:

```text
$ python -c "import os; print(os.name)"
posix
$ python check_production_ready.py
...
     ✅ Docker: build image thành công — 3s
     ✅ Docker: image < 500 MB — 273 MB
     ✅ Docker: container chạy được, GET /health → 200
...
     ✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
     ✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 1.1s
...
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

(Chạy cùng script bằng Python Windows cho kết quả 11/12, vì Windows không gửi được SIGTERM nên mục Graceful shutdown bị ⚠️, đúng như README lưu ý số 2.)

Tóm tắt thiết kế (chi tiết trong code):

| Tiêu chí | Cách làm |
|---|---|
| Dockerfile | 2 stage `python:3.11-slim`: builder cài vào `/opt/venv`, runtime chỉ copy venv + `app/` + `utils/`; user `agent` (uid 10001); `HEALTHCHECK` gọi `/health`; `CMD ["sh","-c","exec uvicorn ... --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2}"]` → uvicorn là PID 1. Image 273 MiB (286 MB) |
| Compose | `agent` (build `.`, `env_file .env required:false`, `REDIS_URL=redis://redis:6379/0`, `depends_on: redis: service_healthy`) + `redis:7-alpine` (healthcheck, AOF, volume) |
| `/health` / `/ready` | `/health` không chạm Redis; `/ready` `PING` Redis (timeout 2s) → 503 nếu lỗi hoặc đang shutdown |
| Auth | `APIKeyHeader(auto_error=False)` + `hmac.compare_digest`; thiếu/sai/chưa cấu hình key → 401 |
| Rate limit | Sliding window 60s bằng Redis sorted set trong **một Lua script** (atomic giữa các worker), key = sha256(API key); 429 + `Retry-After` tính từ request cũ nhất |
| Cost guard | `INCRBYFLOAT` theo ngày + tháng trong Redis; 402 khi vượt `DAILY_BUDGET_USD` / `MONTHLY_BUDGET_USD` |
| Config | `config.py` đọc toàn bộ từ env, không có secret mặc định; `.env.example` liệt kê đủ |
| Logging | `JsonFormatter` (json.dumps cả record), áp cho cả logger của uvicorn trong worker |
| Lỗi | Handler riêng cho HTTP error / validation (422 dạng `{"error","detail","request_id"}`) / Redis down (503) / exception lạ (500, không lộ stack trace) |
| Shutdown | Dựa vào uvicorn (SIGTERM → chờ request xong) + `lifespan` shutdown chờ in-flight, log, đóng Redis |

Kiểm tra thủ công bằng `docker compose` (`RATE_LIMIT_PER_MINUTE=3`):

```text
$ curl -i -X POST /ask (no key)
HTTP/1.1 401 Unauthorized
www-authenticate: ApiKey
{"error":"unauthorized","detail":"Missing or invalid API key (header X-API-Key)","request_id":"690f110411dd491a"}

$ curl -i -X POST /ask -H "X-API-Key: ***" -d '{"question":""}'
HTTP/1.1 422 Unprocessable Entity
{"error":"invalid_request","detail":[{"field":"question","message":"String should have at least 1 character"}],"request_id":"1d3e15c2b44e400d"}

$ curl -i -X POST /ask -H "X-API-Key: ***" -d '{"question":"What is deployment?"}'   # lần 1..3
HTTP/1.1 200 OK
x-ratelimit-limit: 3
x-ratelimit-remaining: 2
{"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","usage":{"input_tokens":4,"output_tokens":21,"cost_usd":1.32e-05},"request_id":"91a5437e79934ec5"}

$ ... lần 4
HTTP/1.1 429 Too Many Requests
retry-after: 60
{"error":"rate_limited","detail":"Rate limit exceeded: 3 requests per minute","request_id":"ddab327c21154741"}

$ docker compose logs agent
{"ts": "2026-11-25T09:54:56.912+00:00", "lvl": "INFO", "logger": "agent", "event": "request", "request_id": "ddab327c21154741", "method": "POST", "path": "/ask", "status": 429, "ms": 3.2}

$ docker compose stop agent
took 1.4s, exit code 0
```

---

## AI log

Theo [RULES.md](RULES.md) mục 1. Toàn bộ bài làm có dùng trợ lý AI (Claude Code, chạy trong VS Code) để: đọc đề, cài môi trường, viết code Part 6, chạy lệnh và soạn nháp câu trả lời. Mọi con số trong bài đều lấy từ lệnh đã chạy thật trên máy (output dán nguyên văn, chỉ che token/key).

| # | Hỏi / giao việc | AI trả về | Kiểm tra / sửa |
|---|---|---|---|
| 1 | Đọc README, RULES, CHECKPOINTS, RUBRIC, `check_production_ready.py`, liệt kê yêu cầu | Danh sách tiêu chí + quy ước script chấm (401 không phải 403/422, `/ready` 503 khi Redis chết, SIGTERM trong WSL...) | Đối chiếu từng mục với bảng "Script chấm dựa vào..." trong `06-lab-complete/README.md` |
| 2 | Cài môi trường | Venv Python 3.11 bằng `uv` cho Windows và WSL (WSL không có pip/sudo nên giải nén binary `uv` từ wheel PyPI); shim `docker` → `docker.exe` trong WSL vì Docker Desktop chưa bật WSL integration | `os.name` in `posix`; script chấm trong WSL build/chạy được image |
| 3 | Viết các TODO Part 6 | Code `config/auth/redis_client/rate_limiter/cost_guard/main.py`, Dockerfile, compose, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml` | Chạy `check_production_ready.py`: trên Windows 11/12 (thiếu SIGTERM), trong WSL **PASS 12/12**; test tay bằng `docker compose` (401/422/429/stop) |
| 4 | Lỗi `"field":"0"` khi body không phải JSON | Bỏ index số trong `loc`, mặc định `"body"` | Gọi lại → `{"field":"body","message":"JSON decode error"}` |
| 5 | Chạy Part 1, 2, 4, 5 và giải thích | Output curl/docker + giải thích | Tự đọc code mẫu; phát hiện thêm: log JSON Part 1 bị nuốt do `logging.warning` trước `basicConfig`; JSON log hỏng ở image Part 2; `budget_remaining_usd` đặt tên sai (Part 4); `turn` lệch +1 (Part 5) |
| 6 | Part 7: thêm metric, load test, eval, sửa KB | Histogram `agent_question_length_chars`; 2 entry KB (HPA, JWT) | Kiểm tra trigger keyword chỉ khớp đúng 2 câu trong golden dataset trước khi thêm; eval cuối 23/23, 0 regression |
| 7 | Stack observability lỗi 502 | Đọc log: `ModuleNotFoundError: uvicorn`. User `agent` có HOME=/app nên Python tìm `/app/.local`; thêm `ENV PYTHONUSERBASE=/home/agent/.local` | Agent healthy, `/ask` qua Nginx 200 |
| 8 | Benchmark scaling ra RPS bất thường | Phát hiện `docker compose run locust` khởi động lại dependency theo `replicas: 2`, làm sai số instance | Đối chiếu `count(up{job="agent"})` trên Prometheus; chạy lại với `--no-deps`, ghi số instance trước/sau mỗi lần chạy |
