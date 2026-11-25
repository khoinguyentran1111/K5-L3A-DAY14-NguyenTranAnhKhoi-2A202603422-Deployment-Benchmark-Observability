# Deployment Information

> Agent được deploy là agent Part 6 trong [`06-lab-complete/`](06-lab-complete/) (đạt `PASS 12/12`), theo CHECKPOINTS CP6.

## Public URL

**https://day14-production-agent-9j3m.onrender.com**

> Gói free của Render cho service "ngủ" sau ~15 phút không có request; request đầu tiên sau đó có thể mất ~30–60 s để khởi động lại.

## Platform

**Render**, deploy bằng **Blueprint** [`06-lab-complete/render.yaml`](06-lab-complete/render.yaml) (Blueprint path `06-lab-complete/render.yaml`, branch `main`, region Singapore):

| Resource | Loại | Trạng thái |
|---|---|---|
| `day14-production-agent` | Web Service, runtime Docker (build `06-lab-complete/Dockerfile`), `healthCheckPath: /health` | Deployed |
| `day14-redis` | Key Value (Valkey 8), chỉ truy cập nội bộ (`ipAllowList: []`) | Available |

`render.yaml` nối `REDIS_URL` của agent tới Key Value bằng `fromService … property: connectionString`; `AGENT_API_KEY` khai báo `sync: false` nên giá trị được nhập trên dashboard lúc tạo Blueprint, không nằm trong repo.
Config tương đương cho Railway: [`06-lab-complete/railway.toml`](06-lab-complete/railway.toml) (so sánh trong `MISSION_ANSWERS.md` Part 3).

## Test Commands

```bash
BASE=https://day14-production-agent-9j3m.onrender.com
AGENT_API_KEY=<key đã đặt trên Render>

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả chạy thật (2026-11-25):

```text
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
200
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
200
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'
401
$ curl ... -H 'X-API-Key: wrong-key' ...            # sai key
401
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'
200

$ curl -sS "$BASE/health"
{"status":"ok","version":"1.0.0","environment":"production","uptime_s":262.4}
$ curl -sS "$BASE/ready"
{"status":"ready","redis":"ok"}
$ curl -sS -o /dev/null -w 'GET /docs -> %{http_code}\n' "$BASE/docs"
GET /docs -> 404          # ENVIRONMENT=production tắt Swagger UI
```

Script chấm (`python check_production_ready.py --public-url https://day14-production-agent-9j3m.onrender.com`):

```text
✅ 12. Public URL ready (Railway / Render config)
     ✅ Có railway.toml hoặc render.yaml (không chỉ toàn comment)
     ✅ railway.toml: builder + healthcheckPath = "/health"
     ✅ render.yaml: web service + healthCheckPath /health
     ✅ render.yaml: secret không ghi thẳng giá trị (generateValue / sync: false)
     ✅ App lắng nghe theo biến PORT do platform cấp
     ✅ Public URL: GET https://day14-production-agent-9j3m.onrender.com/health → 200
```

### Health Check

```bash
curl https://day14-production-agent-9j3m.onrender.com/health
# {"status":"ok","version":"1.0.0","environment":"production","uptime_s":...}
```

### API Test (with authentication)

```bash
curl -X POST https://day14-production-agent-9j3m.onrender.com/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
```

### Rate limit (10 req/phút) → 429

```bash
for i in $(seq 1 12); do
  curl -sS -o /dev/null -w '%{http_code} ' -X POST "$BASE/ask" -H 'Content-Type: application/json' \
       -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"test"}'
done; echo   # 200 ×10 rồi 429
```

## Environment Variables Set

Đặt trên Render (qua `render.yaml` + dashboard), không ghi trong code:

| Biến | Giá trị | Nguồn |
|---|---|---|
| `PORT` | do Render cấp (10000) | Render tự đặt; `CMD` của Dockerfile nghe `${PORT:-8000}` |
| `AGENT_API_KEY` | secret (không ghi ở đây) | `sync: false`, nhập trên dashboard khi tạo Blueprint |
| `REDIS_URL` | connection string nội bộ của `day14-redis` | `fromService` (Key Value) |
| `ENVIRONMENT` | `production` | `render.yaml` |
| `RATE_LIMIT_PER_MINUTE` | `10` | `render.yaml` |
| `DAILY_BUDGET_USD` / `MONTHLY_BUDGET_USD` | `1.0` / `10.0` | `render.yaml` |
| `LOG_LEVEL` | `INFO` | mặc định trong `config.py` |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
